"""WebSocket command router and message dispatch."""

import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from pydantic import ValidationError

from agy_cockpit.backend.config import get_config
from agy_cockpit.backend.domain.enums import ApprovalDecision
from agy_cockpit.backend.ws.connection import ClientSession
from agy_cockpit.backend.ws.protocol import (
    ClientCommand,
    ProtocolErrorCode,
    create_protocol_error,
    create_server_event,
    parse_client_command,
)
from agy_cockpit.backend.ws.replay import ReplayService

logger = logging.getLogger(__name__)

CommandHandler = Callable[[ClientSession, ClientCommand], Coroutine[Any, Any, None]]


class WebSocketRouter:
    """Routes incoming WebSocket commands to registered handlers."""

    def __init__(
        self,
        replay_service: Optional[ReplayService] = None,
        workspace_service: Any = None,
        conversation_service: Any = None,
        run_service: Any = None,
        approval_service: Any = None,
        settings_service: Any = None,
        diff_service: Any = None,
    ):
        self.replay_service = replay_service
        self.workspace_service = workspace_service
        self.conversation_service = conversation_service
        self.run_service = run_service
        self.approval_service = approval_service
        self.settings_service = settings_service
        self.diff_service = diff_service
        self.handlers: Dict[str, CommandHandler] = {}
        self._register_default_handlers()

    def register(self, command_type: str, handler: CommandHandler) -> None:
        self.handlers[command_type] = handler

    def _register_default_handlers(self) -> None:
        self.handlers["hello"] = self._handle_hello
        self.handlers["ping"] = self._handle_ping
        self.handlers["resume_run_stream"] = self._handle_resume_run_stream
        self.handlers["list_workspaces"] = self._handle_list_workspaces
        self.handlers["open_workspace"] = self._handle_open_workspace
        self.handlers["list_conversations"] = self._handle_list_conversations
        self.handlers["create_conversation"] = self._handle_create_conversation
        self.handlers["open_conversation"] = self._handle_open_conversation
        self.handlers["rename_conversation"] = self._handle_rename_conversation
        self.handlers["archive_conversation"] = self._handle_archive_conversation
        self.handlers["send_prompt"] = self._handle_send_prompt
        self.handlers["cancel_run"] = self._handle_cancel_run
        self.handlers["action_approval"] = self._handle_action_approval
        self.handlers["search_workspace"] = self._handle_search_workspace
        self.handlers["update_settings"] = self._handle_update_settings
        self.handlers["get_file_diff"] = self._handle_get_file_diff

    async def _handle_hello(self, session: ClientSession, cmd: ClientCommand) -> None:
        settings_payload = {"default_model": "gemini-3.8-flash-high", "policy_preset": "request-review"}
        if self.settings_service:
            st = await self.settings_service.get_settings()
            settings_payload["default_model"] = st.default_model
            settings_payload["policy_preset"] = st.policy_preset

        payload = {
            "session_id": session.session_id,
            "version": cmd.protocol_version,
            "server_time": cmd.payload.get("client_version") or "0.1.0",
            "default_model": settings_payload["default_model"],
            "policy_preset": settings_payload["policy_preset"],
        }
        event = create_server_event(
            event_type="hello_ack",
            session_id=session.session_id,
            payload=payload,
        )
        await session.send_event(event)

    async def _handle_ping(self, session: ClientSession, cmd: ClientCommand) -> None:
        event = create_server_event(
            event_type="pong",
            session_id=session.session_id,
            payload={},
        )
        await session.send_event(event)

    async def _handle_resume_run_stream(self, session: ClientSession, cmd: ClientCommand) -> None:
        if self.replay_service:
            run_id = cmd.payload.get("run_id") or cmd.run_id
            last_seq = cmd.payload.get("last_seen_sequence")
            if last_seq is None:
                last_seq = cmd.payload.get("after_sequence", 0)
            if run_id:
                await self.replay_service.handle_resume_run_stream(session, run_id, last_seq)
            else:
                err = create_protocol_error(
                    session_id=session.session_id,
                    error_code=ProtocolErrorCode.INVALID_MESSAGE,
                    message="Missing run_id in resume_run_stream command",
                    request_id=cmd.request_id,
                )
                await session.send_event(err)

    async def _handle_list_workspaces(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.workspace_service:
            return
        workspaces = await self.workspace_service.list_workspaces()
        event = create_server_event(
            event_type="workspace_list",
            session_id=session.session_id,
            payload={"workspaces": [ws.model_dump() for ws in workspaces]},
        )
        await session.send_event(event)

    async def _handle_open_workspace(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.workspace_service:
            return
        path = cmd.payload.get("canonical_path")
        ws_id = cmd.payload.get("workspace_id")
        ws = None
        try:
            if path:
                ws = await self.workspace_service.open_workspace(path)
            elif ws_id:
                ws = await self.workspace_service.get_workspace(ws_id)
            if ws:
                event = create_server_event(
                    event_type="workspace_opened",
                    session_id=session.session_id,
                    payload={"workspace": ws.model_dump()},
                )
                await session.send_event(event)
            else:
                err = create_protocol_error(
                    session_id=session.session_id,
                    error_code=ProtocolErrorCode.WORKSPACE_NOT_ALLOWED,
                    message=f"Workspace not found or not accessible.",
                    request_id=cmd.request_id,
                )
                await session.send_event(err)
        except Exception as e:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.WORKSPACE_NOT_ALLOWED,
                message=str(e),
                request_id=cmd.request_id,
            )
            await session.send_event(err)

    async def _handle_list_conversations(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.conversation_service:
            return
        ws_id = cmd.payload.get("workspace_id")
        include_archived = cmd.payload.get("include_archived", False)
        if not ws_id:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="workspace_id is required",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return
        convs = await self.conversation_service.list_conversations(ws_id, include_archived=include_archived)
        event = create_server_event(
            event_type="conversation_list",
            session_id=session.session_id,
            payload={"conversations": [c.model_dump() for c in convs]},
        )
        await session.send_event(event)

    async def _handle_create_conversation(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.conversation_service:
            return
        ws_id = cmd.payload.get("workspace_id")
        title = cmd.payload.get("title", "New Conversation")
        model_slug = cmd.payload.get("model_slug", "gemini-3.8-flash-high")
        if not ws_id:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="workspace_id is required",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        conv = await self.conversation_service.create_conversation(ws_id, title=title, model_slug=model_slug)
        session.active_conversation_id = conv.id
        event = create_server_event(
            event_type="conversation_created",
            session_id=session.session_id,
            conversation_id=conv.id,
            payload={"conversation": conv.model_dump()},
        )
        await session.send_event(event)

    async def _handle_open_conversation(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.conversation_service:
            return
        conv_id = cmd.payload.get("conversation_id") or cmd.conversation_id
        if not conv_id:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="conversation_id is required",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        conv = await self.conversation_service.get_conversation(conv_id)
        if not conv:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.CONVERSATION_NOT_FOUND,
                message=f"Conversation '{conv_id}' not found",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        session.active_conversation_id = conv.id

        # Fetch messages
        from agy_cockpit.backend.db.repositories.message_repository import MessageRepository
        msg_repo = MessageRepository(self.conversation_service.conn)
        messages = await msg_repo.list_by_conversation(conv.id)

        # Check for active run
        active_run = None
        if self.run_service:
            from agy_cockpit.backend.db.repositories.run_repository import RunRepository
            run_repo = RunRepository(self.conversation_service.conn)
            active_run_obj = await run_repo.get_active_for_conversation(conv.id)
            if active_run_obj:
                active_run = active_run_obj.model_dump()

        event = create_server_event(
            event_type="conversation_snapshot",
            session_id=session.session_id,
            conversation_id=conv.id,
            payload={
                "conversation": conv.model_dump(),
                "messages": [m.model_dump() for m in messages],
                "active_run": active_run,
            },
        )
        await session.send_event(event)

    async def _handle_rename_conversation(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.conversation_service:
            return
        conv_id = cmd.payload.get("conversation_id") or cmd.conversation_id
        title = cmd.payload.get("title", "")
        if not conv_id or not title:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="conversation_id and title are required",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return
        try:
            conv = await self.conversation_service.rename_conversation(conv_id, title)
            await self._handle_open_conversation(session, cmd)
        except Exception as e:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.CONVERSATION_NOT_FOUND,
                message=str(e),
                request_id=cmd.request_id,
            )
            await session.send_event(err)

    async def _handle_archive_conversation(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.conversation_service:
            return
        conv_id = cmd.payload.get("conversation_id") or cmd.conversation_id
        if not conv_id:
            return
        await self.conversation_service.archive_conversation(conv_id)

    async def _handle_send_prompt(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.run_service:
            return
        conv_id = cmd.payload.get("conversation_id") or cmd.conversation_id or session.active_conversation_id
        prompt = cmd.payload.get("prompt", "")
        attachment_ids = cmd.payload.get("attachment_ids", [])
        model_slug = cmd.payload.get("model_slug")

        if not conv_id:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="conversation_id is required to send prompt",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        if not prompt or not prompt.strip():
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="Prompt text cannot be empty",
                request_id=cmd.request_id,
                conversation_id=conv_id,
            )
            await session.send_event(err)
            return

        try:
            run = await self.run_service.start_prompt_run(
                session_id=session.session_id,
                conversation_id=conv_id,
                prompt=prompt,
                attachment_ids=attachment_ids,
                model_slug=model_slug,
            )
            session.active_run_id = run.id
        except Exception as e:
            from agy_cockpit.backend.services.run_service import RunAlreadyActiveError
            err_code = (
                ProtocolErrorCode.RUN_ALREADY_ACTIVE
                if isinstance(e, RunAlreadyActiveError)
                else ProtocolErrorCode.INTERNAL_ERROR
            )
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=err_code,
                message=str(e),
                request_id=cmd.request_id,
                conversation_id=conv_id,
            )
            await session.send_event(err)

    async def _handle_cancel_run(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.run_service:
            return
        run_id = cmd.payload.get("run_id") or cmd.run_id or session.active_run_id
        if not run_id:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.RUN_NOT_FOUND,
                message="run_id is required to cancel",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return
        await self.run_service.cancel_run(run_id)

    async def _handle_action_approval(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.approval_service:
            return
        appr_id = cmd.payload.get("approval_request_id")
        decision_str = cmd.payload.get("decision", "").lower()
        if not appr_id or decision_str not in ("approved", "rejected"):
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="Valid approval_request_id and decision ('approved'/'rejected') required",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        decision = (
            ApprovalDecision.APPROVED if decision_str == "approved" else ApprovalDecision.REJECTED
        )
        await self.approval_service.resolve_approval(
            approval_id=appr_id,
            decision=decision,
            session_id=session.session_id,
            conversation_id=cmd.conversation_id or session.active_conversation_id,
            run_id=cmd.run_id or session.active_run_id,
        )

    async def _handle_search_workspace(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.workspace_service:
            return
        ws_id = cmd.payload.get("workspace_id")
        if not ws_id and session.active_conversation_id and self.conversation_service:
            conv = await self.conversation_service.get_conversation(session.active_conversation_id)
            if conv:
                ws_id = conv.workspace_id

        if not ws_id:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.WORKSPACE_NOT_ALLOWED,
                message="workspace_id could not be determined",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        query = cmd.payload.get("query", "")
        limit = cmd.payload.get("limit", 50)
        include_hidden = cmd.payload.get("include_hidden", False)

        results = await self.workspace_service.search_workspace(
            workspace_id=ws_id,
            query=query,
            limit=limit,
            include_hidden=include_hidden,
        )

        event = create_server_event(
            event_type="workspace_search_results",
            session_id=session.session_id,
            payload={"results": results},
        )
        await session.send_event(event)

    async def _handle_update_settings(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.settings_service:
            return
        updated = await self.settings_service.update_settings(cmd.payload)
        event = create_server_event(
            event_type="settings_updated",
            session_id=session.session_id,
            payload={"settings": updated.model_dump()},
        )
        await session.send_event(event)

    async def _handle_get_file_diff(self, session: ClientSession, cmd: ClientCommand) -> None:
        if not self.diff_service:
            return
        file_path = cmd.payload.get("file_path")
        if not file_path:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message="file_path is required",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        workspace_path = None
        conv_id = cmd.conversation_id or session.active_conversation_id
        if conv_id and self.conversation_service and self.workspace_service:
            conv = await self.conversation_service.get_conversation(conv_id)
            if conv:
                ws = await self.workspace_service.get_workspace(conv.workspace_id)
                if ws:
                    workspace_path = ws.canonical_path

        if not workspace_path and self.workspace_service:
            ws_id = cmd.payload.get("workspace_id")
            if ws_id:
                ws = await self.workspace_service.get_workspace(ws_id)
                if ws:
                    workspace_path = ws.canonical_path

        if not workspace_path:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.WORKSPACE_NOT_ALLOWED,
                message="No active workspace found for diff",
                request_id=cmd.request_id,
            )
            await session.send_event(err)
            return

        try:
            diff_data = self.diff_service.get_file_diff(workspace_path, file_path)
            event = create_server_event(
                event_type="file_diff_data",
                session_id=session.session_id,
                conversation_id=conv_id,
                payload={
                    "file_path": diff_data.file_path,
                    "status": diff_data.status,
                    "original_content": diff_data.original_content,
                    "modified_content": diff_data.modified_content,
                    "language": diff_data.language,
                    "is_binary": diff_data.is_binary,
                    "truncated": diff_data.truncated,
                },
            )
            await session.send_event(event)
        except Exception as e:
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.DIFF_UNAVAILABLE,
                message=str(e),
                request_id=cmd.request_id,
            )
            await session.send_event(err)

    async def dispatch(self, session: ClientSession, raw_message: str) -> None:
        """Parses and dispatches a raw client WebSocket message."""
        cfg = get_config()
        if len(raw_message.encode("utf-8")) > cfg.max_payload_bytes:
            logger.warning("Session %s sent message exceeding max payload size", session.session_id)
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message=f"Message size exceeds limit of {cfg.max_payload_bytes} bytes.",
            )
            await session.send_event(err)
            return

        try:
            cmd = parse_client_command(raw_message)
        except ValidationError as ve:
            logger.debug("Validation error on command from session %s: %s", session.session_id, ve)
            is_version_err = any("protocol_version" in str(err.get("loc", ())) for err in ve.errors())
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.PROTOCOL_VERSION_UNSUPPORTED
                if is_version_err
                else ProtocolErrorCode.INVALID_MESSAGE,
                message=f"Invalid message format: {ve}",
            )
            await session.send_event(err)
            return
        except ValueError as ve:
            logger.debug("Value error on command from session %s: %s", session.session_id, ve)
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.PROTOCOL_VERSION_UNSUPPORTED
                if "version" in str(ve).lower()
                else ProtocolErrorCode.INVALID_MESSAGE,
                message=str(ve),
            )
            await session.send_event(err)
            return
        except Exception as e:
            logger.error("Failed to parse JSON command: %s", e)
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INVALID_MESSAGE,
                message=f"Malformed JSON: {e}",
            )
            await session.send_event(err)
            return

        if cmd.conversation_id:
            session.active_conversation_id = cmd.conversation_id
        if cmd.run_id:
            session.active_run_id = cmd.run_id

        handler = self.handlers.get(cmd.type)
        if not handler:
            logger.info("Command '%s' not implemented or registered", cmd.type)
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.NOT_IMPLEMENTED,
                message=f"Command '{cmd.type}' is not yet implemented.",
                request_id=cmd.request_id,
                conversation_id=cmd.conversation_id,
                run_id=cmd.run_id,
            )
            await session.send_event(err)
            return

        try:
            await handler(session, cmd)
        except Exception as e:
            logger.exception("Error executing handler for command '%s': %s", cmd.type, e)
            err = create_protocol_error(
                session_id=session.session_id,
                error_code=ProtocolErrorCode.INTERNAL_ERROR,
                message=f"Internal handler error: {e}",
                request_id=cmd.request_id,
                conversation_id=cmd.conversation_id,
                run_id=cmd.run_id,
            )
            await session.send_event(err)
