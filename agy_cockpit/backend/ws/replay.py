"""Replay and Snapshot service for reconnect recovery."""

import json
import logging
from typing import Any, Dict, List, Optional
import aiosqlite

from agy_cockpit.backend.db.repositories import (
    ApprovalRepository,
    ArtifactRepository,
    EventRepository,
    FileChangeRepository,
    RunRepository,
    SubagentRepository,
    ToolRepository,
)
from agy_cockpit.backend.ws.connection import ClientSession
from agy_cockpit.backend.ws.protocol import ServerEvent, create_server_event

logger = logging.getLogger(__name__)


class ReplayService:
    """Handles event replay and state snapshot generation on reconnection."""

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        self.event_repo = EventRepository(conn)
        self.run_repo = RunRepository(conn)
        self.tool_repo = ToolRepository(conn)
        self.appr_repo = ApprovalRepository(conn)
        self.fc_repo = FileChangeRepository(conn)
        self.sub_repo = SubagentRepository(conn)
        self.art_repo = ArtifactRepository(conn)

    async def handle_resume_run_stream(
        self, session: ClientSession, run_id: str, last_seen_sequence: int
    ) -> None:
        """Executes replay for the specified run starting after last_seen_sequence."""
        run = await self.run_repo.get_by_id(run_id)
        if not run:
            logger.warning("Resume requested for unknown run %s", run_id)
            return

        session.active_run_id = run_id
        session.active_conversation_id = run.conversation_id

        # 1. Fetch replayable events > last_seen_sequence in ascending order
        missed_events = await self.event_repo.get_events_since(
            run_id=run_id,
            last_sequence=last_seen_sequence,
            replayable_only=True,
        )

        # Check if there are missed events or if replay gap is too large/unavailable
        max_seq = await self.event_repo.get_max_sequence(run_id)

        # If missed_events is empty but max_seq > last_seen_sequence (events purged/non-replayable),
        # or if requested last_seen_sequence == 0 and many events exist, we can send snapshot.
        if not missed_events and max_seq > last_seen_sequence:
            logger.info("Replay gap cannot be satisfied from event log; sending sync_state snapshot for run %s", run_id)
            await self.send_sync_state(session, run_id)
            return

        logger.info(
            "Replaying %d missed events for session %s (run %s, seq > %d)",
            len(missed_events),
            session.session_id,
            run_id,
            last_seen_sequence,
        )

        session.is_replaying = True
        session.replay_buffer.clear()
        max_replayed_seq = last_seen_sequence

        try:
            for rec in missed_events:
                try:
                    payload = json.loads(rec.payload_json)
                except Exception:
                    payload = {}
                event = create_server_event(
                    event_type=rec.type,
                    session_id=session.session_id,
                    payload=payload,
                    conversation_id=rec.conversation_id,
                    run_id=rec.run_id,
                    sequence=rec.sequence,
                    event_id=rec.event_id,
                )
                await session.send_event(event)
                if rec.sequence:
                    max_replayed_seq = max(max_replayed_seq, rec.sequence)
        finally:
            await session.flush_replay_buffer(min_sequence=max_replayed_seq)

    async def build_sync_state_payload(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Constructs canonical sync_state snapshot dictionary for a run."""
        run = await self.run_repo.get_by_id(run_id)
        if not run:
            return None

        # Reconstruct accumulated reasoning and output from events
        all_events = await self.event_repo.get_events_since(run_id, last_sequence=0, replayable_only=True)
        reasoning_chunks = []
        token_chunks = []
        for e in all_events:
            try:
                p = json.loads(e.payload_json)
                if e.type == "reasoning_delta" and "delta" in p:
                    reasoning_chunks.append(p["delta"])
                elif e.type == "token_delta" and "delta" in p:
                    token_chunks.append(p["delta"])
            except Exception:
                continue

        reasoning_text = "".join(reasoning_chunks)
        output_text = "".join(token_chunks)

        tools = await self.tool_repo.list_by_run(run_id)
        pending_requests = [a for a in await self.appr_repo.list_by_run(run_id) if a.decision is None]
        pending_appr = pending_requests[0] if pending_requests else None
        changes = await self.fc_repo.list_by_run(run_id)
        subagents = await self.sub_repo.list_by_run(run_id)
        artifacts = await self.art_repo.list_by_run(run_id)
        max_seq = max((e.sequence or 0 for e in all_events), default=0)

        return {
            "run_id": run_id,
            "conversation_id": run.conversation_id,
            "council_events": [json.loads(e.payload_json) for e in all_events if e.type == "council_progress"],
            "state": run.state.value,
            "reasoning": reasoning_text,
            "output": output_text,
            "tools": [
                {
                    "id": t.id,
                    "sdk_tool_name": t.sdk_tool_name,
                    "args": t.parsed_args,
                    "state": t.state.value,
                    "success": t.success,
                    "output_summary": t.output_summary,
                }
                for t in tools
            ],
            "pending_approvals": [{"id": a.id, "sdk_tool_name": a.sdk_tool_name, "args": a.parsed_args, "reason": a.reason} for a in pending_requests],
            "pending_approval": (
                {
                    "id": pending_appr.id,
                    "sdk_tool_name": pending_appr.sdk_tool_name,
                    "args": pending_appr.parsed_args,
                    "reason": pending_appr.reason,
                }
                if pending_appr
                else None
            ),
            "changed_files": [c.file_path for c in changes],
            "subagents": [
                {
                    "id": s.id,
                    "parent_id": s.parent_id,
                    "name_or_role": s.name_or_role,
                    "state": s.state.value,
                    "current_activity": s.current_activity,
                    "depth": s.depth,
                }
                for s in subagents
            ],
            "artifacts": [
                {
                    "id": a.id,
                    "kind": a.kind.value,
                    "name": a.name,
                    "mime_type": a.mime_type,
                    "preview_supported": a.preview_supported,
                }
                for a in artifacts
            ],
            "last_sequence": max_seq,
        }

    async def send_sync_state(self, session: ClientSession, run_id: str) -> None:
        """Emits a canonical sync_state event to the session."""
        payload = await self.build_sync_state_payload(run_id)
        if payload:
            event = create_server_event(
                event_type="sync_state",
                session_id=session.session_id,
                payload=payload,
                run_id=run_id,
                sequence=payload["last_sequence"],
            )
            await session.send_event(event)
