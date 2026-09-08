"""Agent Service managing Google Antigravity SDK lifecycle and streaming."""

import abc
import asyncio
import json
import logging
import os
import shutil
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

import google.antigravity as agy
from google.antigravity.hooks import policy
from google.antigravity.types import BuiltinTools, SessionContinuationMode

from agy_cockpit.backend.domain.enums import RunState
from agy_cockpit.backend.domain.models import utc_now_iso

logger = logging.getLogger(__name__)


class TurnResult:
    """Outcome of an agent turn."""
    def __init__(
        self,
        final_text: str,
        reasoning_text: str,
        state: RunState,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ):
        self.final_text = final_text
        self.reasoning_text = reasoning_text
        self.state = state
        self.error_code = error_code
        self.error_message = error_message
        self.usage = usage


class AntigravityAdapter(abc.ABC):
    """Abstract interface to decouple agent orchestration from specific SDK backend/mock."""

    @abc.abstractmethod
    async def run_turn(
        self,
        conversation_id: str,
        save_dir: str,
        workspace_path: str,
        prompt: str,
        model_slug: str,
        policy_preset: str,
        approval_handler: Callable[[agy.types.ToolCall], Awaitable[bool]],
        on_thought: Callable[[str], Awaitable[None]],
        on_token: Callable[[str], Awaitable[None]],
        on_tool_start: Callable[[str, str, dict], Awaitable[None]],
        on_tool_finish: Callable[[str, str, bool, Optional[str]], Awaitable[None]],
        cancellation_token: asyncio.Event,
        on_tool_log: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_subagent_update: Optional[Callable[[str, Optional[str], str, str, Optional[str], int], Awaitable[None]]] = None,
        attachments: Optional[List[str]] = None,
    ) -> TurnResult:
        pass


class RealSDKAntigravityAdapter(AntigravityAdapter):
    """Production adapter using google.antigravity.Agent."""

    def _build_policies(
        self,
        preset: str,
        approval_handler: Callable[[agy.types.ToolCall], Awaitable[bool]],
    ) -> List[Any]:
        if preset == "always-proceed":
            return [policy.allow_all()]
        elif preset == "strict":
            return [
                policy.allow(BuiltinTools.VIEW_FILE.value),
                policy.allow(BuiltinTools.LIST_DIR.value),
                policy.allow(BuiltinTools.SEARCH_DIR.value),
                policy.allow(BuiltinTools.FIND_FILE.value),
                policy.ask_user(BuiltinTools.RUN_COMMAND.value, handler=approval_handler),
                policy.ask_user(BuiltinTools.CREATE_FILE.value, handler=approval_handler),
                policy.ask_user(BuiltinTools.EDIT_FILE.value, handler=approval_handler),
                policy.deny("*"),
            ]
        else:  # default "request-review"
            return [
                policy.allow(BuiltinTools.VIEW_FILE.value),
                policy.allow(BuiltinTools.LIST_DIR.value),
                policy.allow(BuiltinTools.SEARCH_DIR.value),
                policy.allow(BuiltinTools.FIND_FILE.value),
                policy.allow(BuiltinTools.SEARCH_WEB.value),
                policy.allow(BuiltinTools.READ_URL_CONTENT.value),
                policy.ask_user(BuiltinTools.RUN_COMMAND.value, handler=approval_handler),
                policy.ask_user(BuiltinTools.CREATE_FILE.value, handler=approval_handler),
                policy.ask_user(BuiltinTools.EDIT_FILE.value, handler=approval_handler),
            ]

    async def run_turn(
        self,
        conversation_id: str,
        save_dir: str,
        workspace_path: str,
        prompt: str,
        model_slug: str,
        policy_preset: str,
        approval_handler: Callable[[agy.types.ToolCall], Awaitable[bool]],
        on_thought: Callable[[str], Awaitable[None]],
        on_token: Callable[[str], Awaitable[None]],
        on_tool_start: Callable[[str, str, dict], Awaitable[None]],
        on_tool_finish: Callable[[str, str, bool, Optional[str]], Awaitable[None]],
        cancellation_token: asyncio.Event,
        on_tool_log: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_subagent_update: Optional[Callable[[str, Optional[str], str, str, Optional[str], int], Awaitable[None]]] = None,
        attachments: Optional[List[str]] = None,
    ) -> TurnResult:
        policies = self._build_policies(policy_preset, approval_handler)
        api_key = os.environ.get("GEMINI_API_KEY", "")

        active_tools: Dict[str, str] = {}

        @agy.hooks.post_tool_call
        async def on_post_tool(data: agy.types.ToolResult):
            tool_id = data.id or data.step_id or "tool"
            tool_name = data.name or active_tools.get(tool_id, "tool")
            success = data.error is None and data.exception is None
            summary = str(data.result) if data.result is not None else (str(data.error) if data.error else None)
            if summary and on_tool_log:
                await on_tool_log(tool_id, summary, not success)
            await on_tool_finish(tool_id, tool_name, success, summary)
            if tool_name in ("start_subagent", "invoke_subagent", "define_subagent") and on_subagent_update:
                sa_id = f"subagent-{tool_id}"
                st = "completed" if success else "failed"
                await on_subagent_update(sa_id, None, "Subagent", st, summary, 1)
            active_tools.pop(tool_id, None)

        @agy.hooks.on_tool_error
        async def on_tool_err(data: Any):
            tool_id = getattr(data, "id", None) or "tool"
            tool_name = getattr(data, "name", "tool")
            err_msg = str(getattr(data, "error", data))
            if on_tool_log:
                await on_tool_log(tool_id, err_msg, True)
            await on_tool_finish(tool_id, tool_name, False, err_msg)
            active_tools.pop(tool_id, None)

        config = agy.LocalAgentConfig(
            api_key=api_key or "dummy-key",
            conversation_id=conversation_id,
            session_continuation_mode=SessionContinuationMode.CREATE_OR_RESUME,
            save_dir=save_dir,
            workspaces=[workspace_path],
            model=model_slug,
            policies=policies,
            hooks=[on_post_tool, on_tool_err],
            capabilities=agy.CapabilitiesConfig(
                enable_subagents=True,
            ),
        )

        accumulated_thoughts: List[str] = []
        accumulated_tokens: List[str] = []

        chat_input: Any = prompt
        if attachments:
            media_items = []
            for att_path in attachments:
                if os.path.exists(att_path):
                    try:
                        media_items.append(agy.types.from_file(att_path))
                    except Exception as me:
                        logger.warning("from_file failed on %s: %s, falling back to from_bytes", att_path, me)
                        try:
                            import mimetypes
                            mime, _ = mimetypes.guess_type(att_path)
                            mime_type = mime or "application/octet-stream"
                            with open(att_path, "rb") as f:
                                data = f.read()
                            media_items.append(agy.types.from_bytes(data, mime_type=mime_type))
                        except Exception as e2:
                            logger.error("Failed loading attachment %s via from_bytes: %s", att_path, e2)
            if media_items:
                chat_input = [prompt, *media_items]

        try:
            async with agy.Agent(config) as agent:
                response = await agent.chat(chat_input)

                # Monitor cancellation
                async def watch_cancellation():
                    await cancellation_token.wait()
                    await response.cancel()

                cancel_watcher = asyncio.create_task(watch_cancellation())

                # Concurrently consume reasoning, tokens, and tool calls
                async def consume_thoughts():
                    try:
                        async for th in response.thoughts:
                            accumulated_thoughts.append(th)
                            await on_thought(th)
                    except Exception:
                        pass

                async def consume_tokens():
                    try:
                        async for tok in response:
                            accumulated_tokens.append(tok)
                            await on_token(tok)
                    except Exception:
                        pass

                active_subagents_stack: List[str] = []
                async def consume_tools():
                    try:
                        async for call in response.tool_calls:
                            call_id = call.id or "call"
                            active_tools[call_id] = call.name
                            await on_tool_start(call_id, call.name, call.args)
                            if call.name in ("start_subagent", "invoke_subagent", "define_subagent") and on_subagent_update:
                                args = call.args or {}
                                subagent_items = args.get("Subagents") or args.get("subagents") or []
                                parent_sa_id = active_subagents_stack[-1] if active_subagents_stack else None
                                current_depth = len(active_subagents_stack) + 1
                                if isinstance(subagent_items, list) and subagent_items:
                                    for idx, sa_item in enumerate(subagent_items):
                                        sa_role = sa_item.get("Role") or sa_item.get("role") or sa_item.get("TypeName") or "Subagent"
                                        sa_task = sa_item.get("Prompt") or sa_item.get("prompt") or "Executing subagent task"
                                        sub_id = f"subagent-{call_id}-{idx}"
                                        active_subagents_stack.append(sub_id)
                                        await on_subagent_update(sub_id, parent_sa_id, sa_role, "running", sa_task, current_depth)
                                else:
                                    role = args.get("Role") or args.get("role") or "Subagent"
                                    task = args.get("Prompt") or args.get("task") or args.get("description") or f"Executing {call.name}"
                                    sa_id = f"subagent-{call_id}"
                                    active_subagents_stack.append(sa_id)
                                    await on_subagent_update(sa_id, parent_sa_id, role, "running", task, current_depth)
                    except Exception:
                        pass

                try:
                    await asyncio.gather(
                        consume_thoughts(),
                        consume_tokens(),
                        consume_tools(),
                    )
                finally:
                    cancel_watcher.cancel()
                    for t_id, t_name in list(active_tools.items()):
                        await on_tool_finish(t_id, t_name, True, "Completed")
                        if t_name in ("start_subagent", "invoke_subagent", "define_subagent") and on_subagent_update:
                            await on_subagent_update(f"subagent-{t_id}", None, "Subagent", "completed", "Completed", 1)
                    active_tools.clear()

                if cancellation_token.is_set():
                    return TurnResult(
                        final_text="".join(accumulated_tokens),
                        reasoning_text="".join(accumulated_thoughts),
                        state=RunState.CANCELLED,
                    )

                usage_data = None
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    usage_data = response.usage_metadata.model_dump()

                return TurnResult(
                    final_text="".join(accumulated_tokens),
                    reasoning_text="".join(accumulated_thoughts),
                    state=RunState.COMPLETED,
                    usage=usage_data,
                )

        except asyncio.CancelledError:
            return TurnResult(
                final_text="".join(accumulated_tokens),
                reasoning_text="".join(accumulated_thoughts),
                state=RunState.CANCELLED,
            )
        except Exception as e:
            logger.exception("SDK execution error: %s", e)
            return TurnResult(
                final_text="".join(accumulated_tokens),
                reasoning_text="".join(accumulated_thoughts),
                state=RunState.FAILED,
                error_code="SDK_EXECUTION_ERROR",
                error_message=str(e),
            )


class CLISubscriptionAdapter(AntigravityAdapter):
    """Production adapter using Antigravity CLI (agy) with user's Antigravity subscription session."""

    def __init__(self, agy_binary_path: Optional[str] = None):
        self.agy_path = agy_binary_path or shutil.which("agy") or "agy"

    async def run_turn(
        self,
        conversation_id: str,
        save_dir: str,
        workspace_path: str,
        prompt: str,
        model_slug: str,
        policy_preset: str,
        approval_handler: Callable[[agy.types.ToolCall], Awaitable[bool]],
        on_thought: Callable[[str], Awaitable[None]],
        on_token: Callable[[str], Awaitable[None]],
        on_tool_start: Callable[[str, str, dict], Awaitable[None]],
        on_tool_finish: Callable[[str, str, bool, Optional[str]], Awaitable[None]],
        cancellation_token: asyncio.Event,
        on_tool_log: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_subagent_update: Optional[Callable[[str, Optional[str], str, str, Optional[str], int], Awaitable[None]]] = None,
        attachments: Optional[List[str]] = None,
    ) -> TurnResult:
        full_prompt = prompt
        if attachments:
            att_lines = "\n".join([f"- {p}" for p in attachments])
            full_prompt = f"{prompt}\n\nAttached files for context:\n{att_lines}"

        cmd = [
            self.agy_path,
            "--conversation", conversation_id,
            "--print", full_prompt,
            "--output-format", "stream-json",
            "--add-dir", workspace_path,
        ]
        if model_slug:
            cmd.extend(["--model", model_slug])
        if policy_preset == "always-proceed":
            cmd.append("--dangerously-skip-permissions")

        logger.info(
            "Executing turn via Antigravity CLI subscription: conversation_id=%s, model=%s",
            conversation_id,
            model_slug,
        )

        accumulated_thoughts: List[str] = []
        accumulated_tokens: List[str] = []
        active_tools: Dict[str, str] = {}
        cli_subagents_stack: List[str] = []

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace_path,
            )

            async def watch_cancel():
                await cancellation_token.wait()
                if proc and proc.returncode is None:
                    try:
                        proc.terminate()
                        await asyncio.sleep(0.5)
                        if proc.returncode is None:
                            proc.kill()
                    except Exception:
                        pass

            cancel_task = asyncio.create_task(watch_cancel())

            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                    except Exception:
                        continue

                    event_name = data.get("event") or data.get("type")
                    if event_name == "step_update":
                        step = data.get("step_update", {})
                        delta_obj = data.get("delta") or step.get("delta") or {}
                        step_type = step.get("step_type")
                        state = step.get("state")

                        # Text delta streaming
                        text_chunk = step.get("text_delta") or delta_obj.get("text") or step.get("text")
                        if text_chunk:
                            accumulated_tokens.append(text_chunk)
                            await on_token(text_chunk)

                        # Thinking delta streaming
                        thinking_chunk = delta_obj.get("thinking") or step.get("thinking")
                        if thinking_chunk:
                            accumulated_thoughts.append(thinking_chunk)
                            await on_thought(thinking_chunk)

                        # Delta-based tool calls
                        for tc_data in delta_obj.get("tool_calls", []):
                            tc_id = tc_data.get("id") or f"tool-{len(active_tools)}"
                            tc_name = tc_data.get("name", "tool")
                            tc_args = tc_data.get("args", {})
                            active_tools[tc_id] = tc_name
                            await on_tool_start(tc_id, tc_name, tc_args)

                        if step_type == "agent_response":
                            delta = step.get("text_delta")
                            if delta and not text_chunk:
                                accumulated_tokens.append(delta)
                                await on_token(delta)
                            usage = step.get("usage")
                            if usage and usage.get("thinking_tokens"):
                                th = f"[Thinking: {usage.get('thinking_tokens')} tokens]\n"
                                if th not in accumulated_thoughts:
                                    accumulated_thoughts.append(th)
                                    await on_thought(th)

                        elif step_type == "tool":
                            tool_name = step.get("tool_name") or step.get("tool_info", {}).get("name", "tool")
                            step_idx = step.get("step_index", 0)
                            tool_id = f"tool-{step_idx}-{tool_name}"
                            tool_info = step.get("tool_info", {})

                            if state == "ACTIVE":
                                active_tools[tool_id] = tool_name
                                params = tool_info.get("parameters", {})
                                should_ask = False
                                if policy_preset in ("always-prompt", "strict"):
                                    should_ask = True
                                elif policy_preset in ("ask-destructive", "request-review") or policy_preset != "always-proceed":
                                    should_ask = tool_name in (
                                        "run_command", "write_to_file", "replace_file_content", "create_file", "edit_file"
                                    )

                                if should_ask:
                                    tc = agy.types.ToolCall(id=tool_id, name=tool_name, args=params)
                                    approved = await approval_handler(tc)
                                    if not approved:
                                        await on_tool_start(tool_id, tool_name, params)
                                        await on_tool_finish(tool_id, tool_name, False, "User rejected execution")
                                        active_tools.pop(tool_id, None)
                                        cancellation_token.set()
                                        if proc and proc.returncode is None:
                                            try:
                                                proc.terminate()
                                                await asyncio.sleep(0.1)
                                                if proc.returncode is None:
                                                    proc.kill()
                                            except Exception:
                                                pass
                                        return TurnResult(
                                            final_text="Execution halted: Tool call rejected by user.",
                                            reasoning_text="".join(accumulated_thoughts),
                                            state=RunState.CANCELLED,
                                        )
                                await on_tool_start(tool_id, tool_name, params)

                            elif state in ("DONE", "ERROR"):
                                success = (state == "DONE")
                                out = tool_info.get("output") or ""
                                if not out and isinstance(tool_info.get("error"), dict):
                                    out = tool_info["error"].get("message", "")
                                if out and on_tool_log:
                                    await on_tool_log(tool_id, str(out), not success)
                                await on_tool_finish(tool_id, tool_name, success, str(out)[:500])
                                active_tools.pop(tool_id, None)

                            # Subagent tracking
                            if tool_name in ("invoke_subagent", "define_subagent") and on_subagent_update:
                                subagent_info = step.get("subagent_info") or {}
                                sa_id = subagent_info.get("conversation_id") or f"subagent-{step_idx}"
                                role = subagent_info.get("role") or tool_info.get("parameters", {}).get("Role") or "Subagent"
                                sa_state = "completed" if state == "DONE" else "running"
                                parent_sa_id = subagent_info.get("parent_conversation_id") or (
                                    cli_subagents_stack[-1] if cli_subagents_stack and cli_subagents_stack[-1] != sa_id else None
                                )
                                if sa_id in cli_subagents_stack:
                                    depth = cli_subagents_stack.index(sa_id) + 1
                                else:
                                    depth = len(cli_subagents_stack) + 1

                                if sa_state == "running" and sa_id not in cli_subagents_stack:
                                    cli_subagents_stack.append(sa_id)
                                elif sa_state in ("completed", "done", "failed") and sa_id in cli_subagents_stack:
                                    cli_subagents_stack.remove(sa_id)
                                await on_subagent_update(sa_id, parent_sa_id, role, sa_state, f"Executing {tool_name}", depth)

                    elif event_name == "result":
                        res = data.get("result", {})
                        if isinstance(res, dict):
                            final_text = res.get("response") or res.get("text") or "".join(accumulated_tokens)
                            usage_data = res.get("usage")
                        else:
                            final_text = "".join(accumulated_tokens)
                            usage_data = None
                        await proc.wait()
                        return TurnResult(
                            final_text=final_text,
                            reasoning_text="".join(accumulated_thoughts),
                            state=RunState.COMPLETED,
                            usage=usage_data,
                        )

                await proc.wait()
                if cancellation_token.is_set():
                    return TurnResult(
                        final_text="".join(accumulated_tokens),
                        reasoning_text="".join(accumulated_thoughts),
                        state=RunState.CANCELLED,
                    )
                return TurnResult(
                    final_text="".join(accumulated_tokens),
                    reasoning_text="".join(accumulated_thoughts),
                    state=RunState.COMPLETED,
                )
            finally:
                cancel_task.cancel()
                for t_id, t_name in list(active_tools.items()):
                    await on_tool_finish(t_id, t_name, True, "Completed")
                active_tools.clear()

        except asyncio.CancelledError:
            return TurnResult("".join(accumulated_tokens), "".join(accumulated_thoughts), RunState.CANCELLED)
        except Exception as e:
            logger.exception("CLI subscription execution error: %s", e)
            return TurnResult(
                final_text="".join(accumulated_tokens),
                reasoning_text="".join(accumulated_thoughts),
                state=RunState.FAILED,
                error_code="CLI_EXECUTION_ERROR",
                error_message=str(e),
            )


class UnifiedAntigravityAdapter(AntigravityAdapter):
    """Auto-detecting adapter that bridges the user's Antigravity subscription

    or falls back to the Python SDK if an explicit GEMINI_API_KEY is configured.
    """

    def __init__(
        self,
        cli_adapter: Optional[CLISubscriptionAdapter] = None,
        sdk_adapter: Optional[RealSDKAntigravityAdapter] = None,
    ):
        self.cli_adapter = cli_adapter or CLISubscriptionAdapter()
        self.sdk_adapter = sdk_adapter or RealSDKAntigravityAdapter()

    def _should_use_cli(self) -> bool:
        adapter_mode = os.environ.get("AGY_COCKPIT_ADAPTER", "").lower()
        if adapter_mode == "sdk":
            return False
        if adapter_mode == "cli":
            return True
        has_agy = bool(shutil.which("agy"))
        has_api_key = bool(os.environ.get("GEMINI_API_KEY"))
        has_oauth = os.path.exists(os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token"))
        if has_agy and (has_oauth or not has_api_key):
            return True
        return False

    async def run_turn(
        self,
        conversation_id: str,
        save_dir: str,
        workspace_path: str,
        prompt: str,
        model_slug: str,
        policy_preset: str,
        approval_handler: Callable[[agy.types.ToolCall], Awaitable[bool]],
        on_thought: Callable[[str], Awaitable[None]],
        on_token: Callable[[str], Awaitable[None]],
        on_tool_start: Callable[[str, str, dict], Awaitable[None]],
        on_tool_finish: Callable[[str, str, bool, Optional[str]], Awaitable[None]],
        cancellation_token: asyncio.Event,
        on_tool_log: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_subagent_update: Optional[Callable[[str, Optional[str], str, str, Optional[str], int], Awaitable[None]]] = None,
        attachments: Optional[List[str]] = None,
    ) -> TurnResult:
        if self._should_use_cli():
            logger.info("Using CLISubscriptionAdapter for Antigravity subscription session")
            res = await self.cli_adapter.run_turn(
                conversation_id=conversation_id,
                save_dir=save_dir,
                workspace_path=workspace_path,
                prompt=prompt,
                model_slug=model_slug,
                policy_preset=policy_preset,
                approval_handler=approval_handler,
                on_thought=on_thought,
                on_token=on_token,
                on_tool_start=on_tool_start,
                on_tool_finish=on_tool_finish,
                cancellation_token=cancellation_token,
                on_tool_log=on_tool_log,
                on_subagent_update=on_subagent_update,
                attachments=attachments,
            )
            if res.state != RunState.FAILED or not os.environ.get("GEMINI_API_KEY"):
                return res
            logger.warning(
                "CLI subscription adapter failed (%s); falling back to SDK adapter",
                res.error_message,
            )

        return await self.sdk_adapter.run_turn(
            conversation_id=conversation_id,
            save_dir=save_dir,
            workspace_path=workspace_path,
            prompt=prompt,
            model_slug=model_slug,
            policy_preset=policy_preset,
            approval_handler=approval_handler,
            on_thought=on_thought,
            on_token=on_token,
            on_tool_start=on_tool_start,
            on_tool_finish=on_tool_finish,
            cancellation_token=cancellation_token,
            on_tool_log=on_tool_log,
            on_subagent_update=on_subagent_update,
            attachments=attachments,
        )


class MockAntigravityAdapter(AntigravityAdapter):
    """Deterministic mock adapter for headless testing without live model quotas."""

    def __init__(
        self,
        thoughts: Optional[List[str]] = None,
        tokens: Optional[List[str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_logs: Optional[Dict[str, List[str]]] = None,
        subagents: Optional[List[Dict[str, Any]]] = None,
        delay: float = 0.01,
        requires_approval: bool = False,
        wait_for_cancel: bool = False,
    ):
        self.thoughts = thoughts or ["Analyzing requirements...", "Formulating plan..."]
        self.tokens = tokens or ["Hello! ", "I am ready ", "to help you."]
        self.tools = tools or []
        self.tool_logs = tool_logs or {}
        self.subagents = subagents or []
        self.delay = delay
        self.requires_approval = requires_approval
        self.wait_for_cancel = wait_for_cancel

    async def run_turn(
        self,
        conversation_id: str,
        save_dir: str,
        workspace_path: str,
        prompt: str,
        model_slug: str,
        policy_preset: str,
        approval_handler: Callable[[agy.types.ToolCall], Awaitable[bool]],
        on_thought: Callable[[str], Awaitable[None]],
        on_token: Callable[[str], Awaitable[None]],
        on_tool_start: Callable[[str, str, dict], Awaitable[None]],
        on_tool_finish: Callable[[str, str, bool, Optional[str]], Awaitable[None]],
        cancellation_token: asyncio.Event,
        on_tool_log: Optional[Callable[[str, str, bool], Awaitable[None]]] = None,
        on_subagent_update: Optional[Callable[[str, Optional[str], str, str, Optional[str], int], Awaitable[None]]] = None,
        attachments: Optional[List[str]] = None,
    ) -> TurnResult:
        accumulated_thoughts = []
        accumulated_tokens = []

        # 1. Emit thoughts
        for th in self.thoughts:
            if cancellation_token.is_set():
                return TurnResult("".join(accumulated_tokens), "".join(accumulated_thoughts), RunState.CANCELLED)
            accumulated_thoughts.append(th)
            await on_thought(th)
            if self.delay:
                await asyncio.sleep(self.delay)

        if self.wait_for_cancel:
            await cancellation_token.wait()
            return TurnResult("".join(accumulated_tokens), "".join(accumulated_thoughts), RunState.CANCELLED)

        # 1.5 Emit subagent updates if configured
        if on_subagent_update and self.subagents:
            for sa in self.subagents:
                sa_id = sa.get("id", "sa-1")
                p_id = sa.get("parent_id")
                name = sa.get("name_or_role", "Researcher")
                state = sa.get("state", "running")
                act = sa.get("current_activity", "Analyzing...")
                depth = sa.get("depth", 1)
                await on_subagent_update(sa_id, p_id, name, state, act, depth)
                if self.delay:
                    await asyncio.sleep(self.delay)

        # 2. Emit tools if configured
        for t in self.tools:
            if cancellation_token.is_set():
                return TurnResult("".join(accumulated_tokens), "".join(accumulated_thoughts), RunState.CANCELLED)
            t_id = t.get("id", "tool-1")
            t_name = t.get("name", "list_directory")
            t_args = t.get("args", {"directory_path": "."})

            # Check approval if required
            if self.requires_approval or t.get("requires_approval"):
                tc = agy.types.ToolCall(id=t_id, name=t_name, args=t_args)
                approved = await approval_handler(tc)
                if not approved:
                    await on_tool_start(t_id, t_name, t_args)
                    await on_tool_finish(t_id, t_name, False, "User rejected execution")
                    continue

            await on_tool_start(t_id, t_name, t_args)

            # Emit tool logs if provided
            if on_tool_log and t_id in self.tool_logs:
                for chunk in self.tool_logs[t_id]:
                    await on_tool_log(t_id, chunk, False)

            # Apply mock file change if create_file or edit_file
            if t_name in ("create_file", "edit_file"):
                rel_p = t_args.get("target_path") or t_args.get("file_path") or t_args.get("path")
                new_content = t_args.get("content", "modified content")
                if rel_p and workspace_path:
                    abs_p = os.path.join(workspace_path, rel_p)
                    os.makedirs(os.path.dirname(abs_p), exist_ok=True)
                    with open(abs_p, "w", encoding="utf-8") as f:
                        f.write(new_content)

            if self.delay:
                await asyncio.sleep(self.delay)
            await on_tool_finish(t_id, t_name, True, "Executed successfully")

        # 3. Emit tokens
        for tok in self.tokens:
            if cancellation_token.is_set():
                return TurnResult("".join(accumulated_tokens), "".join(accumulated_thoughts), RunState.CANCELLED)
            accumulated_tokens.append(tok)
            await on_token(tok)
            if self.delay:
                await asyncio.sleep(self.delay)

        return TurnResult(
            final_text="".join(accumulated_tokens),
            reasoning_text="".join(accumulated_thoughts),
            state=RunState.COMPLETED,
            usage={"prompt_tokens": 10, "candidates_tokens": len(self.tokens)},
        )
