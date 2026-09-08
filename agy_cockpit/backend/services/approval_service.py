"""Approval service bridging SDK policies and user approval UI."""

import asyncio
import json
import logging
from typing import Dict, Optional
import aiosqlite

from agy_cockpit.backend.db.repositories.approval_repository import ApprovalRepository
from agy_cockpit.backend.domain.enums import ApprovalDecision
from agy_cockpit.backend.domain.models import ApprovalRequest, utc_now_iso
from agy_cockpit.backend.services.event_service import EventService

logger = logging.getLogger(__name__)


class PendingApproval:
    def __init__(self, request: ApprovalRequest, future: asyncio.Future[bool]):
        self.request = request
        self.future = future


class ApprovalService:
    """Manages pending human-in-the-loop tool approvals."""

    def __init__(self, conn: aiosqlite.Connection, event_service: EventService, default_timeout: float = 300.0):
        self.conn = conn
        self.event_repo = ApprovalRepository(conn)
        self.event_service = event_service
        self.default_timeout = default_timeout
        self._pending: Dict[str, PendingApproval] = {}

    async def request_approval(
        self,
        session_id: str,
        run_id: str,
        sdk_tool_name: str,
        args: dict,
        tool_execution_id: Optional[str] = None,
        reason: Optional[str] = None,
        conversation_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        """Called by SDK policy ask_user handler. Pauses execution until browser responds or times out."""
        now = utc_now_iso()
        req = ApprovalRequest(
            run_id=run_id,
            tool_execution_id=tool_execution_id,
            sdk_tool_name=sdk_tool_name,
            args_json=json.dumps(args),
            reason=reason or f"Approval required to run tool '{sdk_tool_name}'",
            created_at=now,
        )
        await self.event_repo.create(req)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[req.id] = PendingApproval(req, future)

        # Emit approval_required event
        await self.event_service.emit_event(
            event_type="approval_required",
            session_id=session_id,
            payload={
                "approval_request_id": req.id,
                "tool_execution_id": tool_execution_id,
                "sdk_tool_name": sdk_tool_name,
                "args": args,
                "reason": req.reason,
            },
            conversation_id=conversation_id,
            run_id=run_id,
            replayable=True,
        )

        effective_timeout = timeout or self.default_timeout
        try:
            approved = await asyncio.wait_for(future, timeout=effective_timeout)
            return approved
        except asyncio.TimeoutError:
            logger.warning("Approval request %s timed out after %fs", req.id, effective_timeout)
            await self.resolve_approval(req.id, ApprovalDecision.TIMEOUT, session_id, conversation_id, run_id)
            return False
        except asyncio.CancelledError:
            logger.info("Approval request %s cancelled due to run cancellation", req.id)
            await self.resolve_approval(req.id, ApprovalDecision.CANCELLED, session_id, conversation_id, run_id)
            raise
        finally:
            self._pending.pop(req.id, None)

    async def resolve_approval(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        session_id: str = "system",
        conversation_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> bool:
        """Resolves a pending approval with user's decision."""
        pending = self._pending.get(approval_id)
        now = utc_now_iso()

        await self.event_repo.resolve(approval_id, decision, now)

        if pending and not pending.future.done():
            is_allow = (decision == ApprovalDecision.APPROVED)
            pending.future.set_result(is_allow)

        # Emit approval_resolved event
        actual_run_id = run_id or (pending.request.run_id if pending else None)
        await self.event_service.emit_event(
            event_type="approval_resolved",
            session_id=session_id,
            payload={
                "approval_request_id": approval_id,
                "decision": decision.value,
            },
            conversation_id=conversation_id,
            run_id=actual_run_id,
            replayable=True,
        )
        return True

    def cancel_pending_for_run(self, run_id: str) -> None:
        """Cancels all pending approvals for a given run."""
        for appr_id, pending in list(self._pending.items()):
            if pending.request.run_id == run_id:
                if not pending.future.done():
                    pending.future.cancel()
                self._pending.pop(appr_id, None)
