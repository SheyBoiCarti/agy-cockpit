"""Agent Service managing Google Antigravity SDK lifecycle and streaming."""

import abc
import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

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
    ) -> TurnResult:
        policies = self._build_policies(policy_preset, approval_handler)
        api_key = os.environ.get("GEMINI_API_KEY", "dummy-key")

        config = agy.LocalAgentConfig(
            api_key=api_key,
            conversation_id=conversation_id,
            session_continuation_mode=SessionContinuationMode.CREATE_OR_RESUME,
            save_dir=save_dir,
            workspaces=[workspace_path],
            model=model_slug,
            policies=policies,
            capabilities=agy.CapabilitiesConfig(
                enable_subagents=True,
            ),
        )

        accumulated_thoughts: List[str] = []
        accumulated_tokens: List[str] = []

        try:
            async with agy.Agent(config) as agent:
                response = await agent.chat(prompt)

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

                async def consume_tools():
                    try:
                        async for call in response.tool_calls:
                            await on_tool_start(call.id or "call", call.name, call.args)
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
