"""Run Service coordinating agent turn execution, streaming, approvals, and cancellation."""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional
import aiosqlite

from agy_cockpit.backend.db.repositories import (
    ArtifactRepository,
    AttachmentRepository,
    ConversationRepository,
    FileChangeRepository,
    MessageRepository,
    RunRepository,
    SettingsRepository,
    SubagentRepository,
    ToolRepository,
    WorkspaceRepository,
)
from agy_cockpit.backend.domain.enums import (
    ArtifactKind,
    FileChangeStatus,
    MessageRole,
    RunState,
    SubagentState,
    ToolExecutionState,
)
from agy_cockpit.backend.domain.models import (
    Artifact,
    Attachment,
    FileChange,
    Message,
    Run,
    SubagentNode,
    ToolExecution,
    utc_now_iso,
)
from agy_cockpit.backend.services.agent_service import (
    AntigravityAdapter,
    RealSDKAntigravityAdapter,
    UnifiedAntigravityAdapter,
)
from agy_cockpit.backend.services.approval_service import ApprovalService
from agy_cockpit.backend.services.diff_service import DiffService
from agy_cockpit.backend.services.event_service import EventService
from agy_cockpit.backend.ws.protocol import ProtocolErrorCode

logger = logging.getLogger(__name__)


class RunAlreadyActiveError(Exception):
    pass


class ActiveRunContext:
    def __init__(self, run: Run, task: asyncio.Task, cancel_token: asyncio.Event):
        self.run = run
        self.task = task
        self.cancel_token = cancel_token


class RunService:
    """Orchestrates agent turns from user prompt to final completion."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        event_service: EventService,
        approval_service: ApprovalService,
        adapter: Optional[AntigravityAdapter] = None,
        diff_service: Optional[DiffService] = None,
    ):
        self.conn = conn
        self.event_service = event_service
        self.approval_service = approval_service
        self.adapter = adapter or UnifiedAntigravityAdapter()
        self.diff_service = diff_service or DiffService()

        self.run_repo = RunRepository(conn)
        self.conv_repo = ConversationRepository(conn)
        self.msg_repo = MessageRepository(conn)
        self.tool_repo = ToolRepository(conn)
        self.ws_repo = WorkspaceRepository(conn)
        self.settings_repo = SettingsRepository(conn)
        self.file_change_repo = FileChangeRepository(conn)
        self.subagent_repo = SubagentRepository(conn)
        self.attachment_repo = AttachmentRepository(conn)
        self.artifact_repo = ArtifactRepository(conn)

        self._active_runs: Dict[str, ActiveRunContext] = {}

    def is_run_active(self, run_id: str) -> bool:
        return run_id in self._active_runs

    async def start_prompt_run(
        self,
        session_id: str,
        conversation_id: str,
        prompt: str,
        attachment_ids: Optional[List[str]] = None,
        model_slug: Optional[str] = None,
    ) -> Run:
        """Initiates an execution turn for a prompt."""
        # 1. Validate conversation and workspace
        conv = await self.conv_repo.get_by_id(conversation_id)
        if not conv:
            raise ValueError(f"Conversation '{conversation_id}' not found.")

        ws = await self.ws_repo.get_by_id(conv.workspace_id)
        if not ws:
            raise ValueError(f"Workspace '{conv.workspace_id}' not found.")

        # 2. Validate attachments if provided
        if attachment_ids:
            for att_id in attachment_ids:
                att = await self.attachment_repo.get_by_id(att_id)
                if not att or att.conversation_id != conversation_id:
                    raise ValueError(
                        f"Attachment '{att_id}' not found or does not belong to conversation '{conversation_id}'."
                    )

        # 3. Check for existing active run in this conversation
        existing_run = await self.run_repo.get_active_for_conversation(conversation_id)
        if existing_run and existing_run.id in self._active_runs:
            raise RunAlreadyActiveError(
                f"Conversation '{conversation_id}' already has an active run ({existing_run.id})."
            )

        # 4. Persist user message
        now = utc_now_iso()
        user_msg = Message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            author_time=now,
            content=prompt,
            attachment_ids=attachment_ids or [],
        )
        await self.msg_repo.create(user_msg)

        # 4. Create Run in QUEUED state
        run = Run(
            conversation_id=conversation_id,
            user_message_id=user_msg.id,
            state=RunState.QUEUED,
            started_at=now,
        )
        await self.run_repo.create(run)

        # 5. Emit run_started event
        await self.event_service.emit_event(
            event_type="run_started",
            session_id=session_id,
            payload={
                "run_id": run.id,
                "conversation_id": conversation_id,
                "user_message_id": user_msg.id,
                "started_at": run.started_at,
            },
            conversation_id=conversation_id,
            run_id=run.id,
            replayable=True,
        )

        # 6. Resolve attachment paths and launch execution task
        attachment_paths: List[str] = []
        if attachment_ids:
            for att_id in attachment_ids:
                att = await self.attachment_repo.get_by_id(att_id)
                if att and att.file_path and os.path.exists(att.file_path):
                    attachment_paths.append(att.file_path)

        cancel_token = asyncio.Event()
        task = asyncio.create_task(
            self._execute_turn(
                session_id=session_id,
                run=run,
                conv=conv,
                workspace_path=ws.canonical_path,
                prompt=prompt,
                model_slug=model_slug or conv.model_slug,
                cancel_token=cancel_token,
                attachments=attachment_paths,
            )
        )

        self._active_runs[run.id] = ActiveRunContext(run, task, cancel_token)
        return run

    async def _execute_turn(
        self,
        session_id: str,
        run: Run,
        conv: Any,
        workspace_path: str,
        prompt: str,
        model_slug: str,
        cancel_token: asyncio.Event,
        attachments: Optional[List[str]] = None,
    ) -> None:
        """Executes the agent turn and translates events."""
        settings = await self.settings_repo.get()
        policy_preset = settings.policy_preset

        # Callbacks for streaming translation
        async def on_thought(thought_text: str):
            if run.state != RunState.THINKING and not run.state.is_terminal:
                await self._transition_state(run, RunState.THINKING)
            await self.event_service.emit_event(
                event_type="reasoning_delta",
                session_id=session_id,
                payload={"delta": thought_text},
                conversation_id=conv.id,
                run_id=run.id,
                replayable=True,
            )

        async def on_token(token_text: str):
            if run.state != RunState.STREAMING and not run.state.is_terminal:
                await self._transition_state(run, RunState.STREAMING)
            await self.event_service.emit_event(
                event_type="token_delta",
                session_id=session_id,
                payload={"delta": token_text},
                conversation_id=conv.id,
                run_id=run.id,
                replayable=True,
            )

        async def on_tool_start(tool_id: str, tool_name: str, args: dict):
            if run.state != RunState.RUNNING_TOOL and not run.state.is_terminal:
                await self._transition_state(run, RunState.RUNNING_TOOL)

            tool_rec = ToolExecution(
                id=tool_id,
                run_id=run.id,
                sdk_tool_name=tool_name,
                args_json=json.dumps(args),
                state=ToolExecutionState.STARTED,
                started_at=utc_now_iso(),
            )
            await self.tool_repo.create(tool_rec)

            # Pre-edit snapshot for diff tracking
            file_mutating_tools = (
                "create_file", "edit_file", "write_to_file", "replace_file_content", "multi_replace_file_content"
            )
            if tool_name in file_mutating_tools and self.diff_service:
                target_p = (
                    args.get("target_path")
                    or args.get("file_path")
                    or args.get("path")
                    or args.get("TargetFile")
                    or args.get("target_file")
                )
                if target_p:
                    self.diff_service.capture_pre_edit_snapshot(workspace_path, str(target_p))

            await self.event_service.emit_event(
                event_type="tool_started",
                session_id=session_id,
                payload={
                    "tool_execution_id": tool_id,
                    "sdk_tool_name": tool_name,
                    "args": args,
                },
                conversation_id=conv.id,
                run_id=run.id,
                replayable=True,
            )

        async def on_tool_log(tool_id: str, chunk: str, is_stderr: bool = False):
            await self.event_service.emit_event(
                event_type="tool_log",
                session_id=session_id,
                payload={
                    "tool_execution_id": tool_id,
                    "chunk": chunk,
                    "is_stderr": is_stderr,
                },
                conversation_id=conv.id,
                run_id=run.id,
                replayable=True,
            )

        async def on_tool_finish(tool_id: str, tool_name: str, success: bool, summary: Optional[str]):
            await self.tool_repo.complete(
                tool_id=tool_id,
                state=ToolExecutionState.COMPLETED if success else ToolExecutionState.FAILED,
                finished_at=utc_now_iso(),
                success=success,
                output_summary=summary,
            )
            await self.event_service.emit_event(
                event_type="tool_finished",
                session_id=session_id,
                payload={
                    "tool_execution_id": tool_id,
                    "sdk_tool_name": tool_name,
                    "success": success,
                    "output_summary": summary,
                },
                conversation_id=conv.id,
                run_id=run.id,
                replayable=True,
            )

            # Track file changes and register artifacts
            file_mutating_tools = (
                "create_file", "edit_file", "write_to_file", "replace_file_content", "multi_replace_file_content", "generate_image"
            )
            if success and tool_name in file_mutating_tools:
                tool_rec = await self.tool_repo.get_by_id(tool_id)
                if tool_rec:
                    try:
                        args = json.loads(tool_rec.args_json)
                    except Exception:
                        args = {}
                    target_p = (
                        args.get("target_path")
                        or args.get("file_path")
                        or args.get("path")
                        or args.get("TargetFile")
                        or args.get("target_file")
                        or args.get("ImageName")
                    )
                    if target_p:
                        clean_target = str(target_p)
                        if self.diff_service and "image" not in tool_name.lower():
                            diff = self.diff_service.get_file_diff(workspace_path, clean_target)
                            clean_target = diff.file_path
                            status_val = (
                                diff.status
                                if diff.status in ("added", "modified", "deleted", "renamed")
                                else "modified"
                            )
                            fc = FileChange(
                                run_id=run.id,
                                file_path=clean_target,
                                status=FileChangeStatus(status_val),
                                timestamp=utc_now_iso(),
                            )
                            await self.file_change_repo.create(fc)
                            await self.event_service.emit_event(
                                event_type="file_changed",
                                session_id=session_id,
                                payload={
                                    "file_path": clean_target,
                                    "status": status_val,
                                    "run_id": run.id,
                                },
                                conversation_id=conv.id,
                                run_id=run.id,
                                replayable=True,
                            )

                        # Create and emit Artifact
                        abs_target = (
                            os.path.abspath(os.path.join(workspace_path, clean_target))
                            if not os.path.isabs(clean_target)
                            else clean_target
                        )
                        art_kind = ArtifactKind.IMAGE if "image" in tool_name.lower() else ArtifactKind.FILE
                        art = Artifact(
                            run_id=run.id,
                            kind=art_kind,
                            name=os.path.basename(clean_target),
                            mime_type="image/png" if art_kind == ArtifactKind.IMAGE else "text/plain",
                            path_or_storage_key=abs_target,
                            preview_supported=True,
                            created_at=utc_now_iso(),
                            updated_at=utc_now_iso(),
                        )
                        await self.artifact_repo.create(art)
                        await self.event_service.emit_event(
                            event_type="artifact_created",
                            session_id=session_id,
                            payload={
                                "id": art.id,
                                "run_id": art.run_id,
                                "kind": art.kind.value,
                                "name": art.name,
                                "mime_type": art.mime_type,
                                "path_or_storage_key": art.path_or_storage_key,
                                "preview_supported": art.preview_supported,
                                "created_at": art.created_at,
                                "updated_at": art.updated_at,
                            },
                            conversation_id=conv.id,
                            run_id=run.id,
                            replayable=True,
                        )

        async def on_subagent_update(
            subagent_id: str,
            parent_id: Optional[str],
            name_or_role: str,
            state: str,
            current_activity: Optional[str],
            depth: int,
        ):
            sub_state = (
                SubagentState(state)
                if state in [s.value for s in SubagentState]
                else SubagentState.RUNNING
            )
            node = SubagentNode(
                id=subagent_id,
                run_id=run.id,
                parent_id=parent_id,
                name_or_role=name_or_role,
                state=sub_state,
                current_activity=current_activity,
                depth=depth,
                started_at=utc_now_iso(),
            )
            await self.subagent_repo.upsert(node)

            await self.event_service.emit_event(
                event_type="subagent_update",
                session_id=session_id,
                payload={
                    "id": subagent_id,
                    "parent_id": parent_id,
                    "name_or_role": name_or_role,
                    "state": state,
                    "current_activity": current_activity,
                    "depth": depth,
                },
                conversation_id=conv.id,
                run_id=run.id,
                replayable=True,
            )

        async def approval_handler(tool_call: Any) -> bool:
            if not run.state.is_terminal:
                await self._transition_state(run, RunState.WAITING_APPROVAL)
            approved = await self.approval_service.request_approval(
                session_id=session_id,
                run_id=run.id,
                sdk_tool_name=tool_call.name,
                args=tool_call.args,
                tool_execution_id=tool_call.id,
                conversation_id=conv.id,
            )
            return approved

        try:
            # Delegate to adapter
            result = await self.adapter.run_turn(
                conversation_id=conv.id,
                save_dir=conv.sdk_save_dir or f"/tmp/sessions/{conv.id}",
                workspace_path=workspace_path,
                prompt=prompt,
                model_slug=model_slug,
                policy_preset=policy_preset,
                approval_handler=approval_handler,
                on_thought=on_thought,
                on_token=on_token,
                on_tool_start=on_tool_start,
                on_tool_finish=on_tool_finish,
                cancellation_token=cancel_token,
                on_tool_log=on_tool_log,
                on_subagent_update=on_subagent_update,
                attachments=attachments,
            )

            now = utc_now_iso()
            # If final answer produced, persist assistant message
            if result.final_text:
                asst_msg = Message(
                    conversation_id=conv.id,
                    role=MessageRole.ASSISTANT,
                    author_time=now,
                    content=result.final_text,
                )
                await self.msg_repo.create(asst_msg)

            # Transition to terminal state
            terminal_state = result.state
            if cancel_token.is_set():
                terminal_state = RunState.CANCELLED

            await self._finalize_run(
                session_id=session_id,
                run=run,
                conv_id=conv.id,
                terminal_state=terminal_state,
                completed_at=now,
                error_code=result.error_code,
                error_message=result.error_message,
                usage=result.usage,
            )

        except asyncio.CancelledError:
            now = utc_now_iso()
            await asyncio.shield(
                self._finalize_run(
                    session_id=session_id,
                    run=run,
                    conv_id=conv.id,
                    terminal_state=RunState.CANCELLED,
                    completed_at=now,
                )
            )
        except Exception as e:
            logger.exception("Unexpected error in run %s: %s", run.id, e)
            now = utc_now_iso()
            await self._finalize_run(
                session_id=session_id,
                run=run,
                conv_id=conv.id,
                terminal_state=RunState.FAILED,
                completed_at=now,
                error_code="INTERNAL_ERROR",
                error_message=str(e),
            )
        finally:
            self._active_runs.pop(run.id, None)

    async def _transition_state(self, run: Run, new_state: RunState) -> None:
        try:
            await self.run_repo.update_state(run.id, new_state)
            run.state = new_state
        except Exception as e:
            logger.error("Failed transition to %s: %s", new_state, e)

    async def _finalize_run(
        self,
        session_id: str,
        run: Run,
        conv_id: str,
        terminal_state: RunState,
        completed_at: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Transitions run to exactly one terminal state and emits terminal event."""
        # Clean up any pending approvals
        self.approval_service.cancel_pending_for_run(run.id)

        await self.run_repo.update_state(
            run_id=run.id,
            new_state=terminal_state,
            completed_at=completed_at,
            error_code=error_code,
            error_message=error_message,
        )
        run.state = terminal_state
        run.completed_at = completed_at

        if terminal_state == RunState.COMPLETED:
            await self.event_service.emit_event(
                event_type="run_completed",
                session_id=session_id,
                payload={
                    "run_id": run.id,
                    "completed_at": completed_at,
                    "usage": usage or {},
                },
                conversation_id=conv_id,
                run_id=run.id,
                replayable=True,
            )
        elif terminal_state == RunState.CANCELLED:
            await self.event_service.emit_event(
                event_type="run_cancelled",
                session_id=session_id,
                payload={
                    "run_id": run.id,
                    "cancelled_at": completed_at,
                },
                conversation_id=conv_id,
                run_id=run.id,
                replayable=True,
            )
        else:  # FAILED or INTERRUPTED
            await self.event_service.emit_event(
                event_type="run_failed",
                session_id=session_id,
                payload={
                    "run_id": run.id,
                    "error_code": error_code or "RUN_FAILED",
                    "error_message": error_message or "Execution failed",
                    "failed_at": completed_at,
                },
                conversation_id=conv_id,
                run_id=run.id,
                replayable=True,
            )

    async def cancel_run(self, run_id: str) -> bool:
        """Idempotently cancels an active run."""
        active_ctx = self._active_runs.get(run_id)
        now = utc_now_iso()
        await self.run_repo.mark_cancel_requested(run_id, now)

        if active_ctx:
            active_ctx.cancel_token.set()
            self.approval_service.cancel_pending_for_run(run_id)
            return True

        # Run might already be stopped or not in active map
        run = await self.run_repo.get_by_id(run_id)
        if run and not run.state.is_terminal:
            await self.run_repo.update_state(run_id, RunState.CANCELLED, completed_at=now)
            return True
        return False
