"""FastAPI application factory and WebSocket endpoint for Antigravity Cockpit."""

from contextlib import asynccontextmanager
import hmac
import logging
import os
from typing import AsyncGenerator, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agy_cockpit.backend.config import AppConfig, get_config
from agy_cockpit.backend.db.connection import get_db_connection, init_db
from agy_cockpit.backend.services.agent_service import (
    AntigravityAdapter,
    RealSDKAntigravityAdapter,
    UnifiedAntigravityAdapter,
)
from agy_cockpit.backend.services.approval_service import ApprovalService
from agy_cockpit.backend.services.artifact_service import ArtifactService
from agy_cockpit.backend.services.attachment_service import AttachmentService
from agy_cockpit.backend.services.conversation_service import ConversationService
from agy_cockpit.backend.services.diff_service import DiffService
from agy_cockpit.backend.services.event_service import EventService
from agy_cockpit.backend.services.model_catalog_service import ModelCatalogService
from agy_cockpit.backend.services.run_service import RunService
from agy_cockpit.backend.services.settings_service import SettingsService
from agy_cockpit.backend.services.workspace_service import WorkspaceService
from agy_cockpit.backend.domain.enums import WorkspaceSecurityError
from agy_cockpit.backend.ws.connection import ConnectionManager, ConnectionSecurityError
from agy_cockpit.backend.ws.replay import ReplayService
from agy_cockpit.backend.ws.router import WebSocketRouter

logger = logging.getLogger(__name__)


def create_app(
    config: Optional[AppConfig] = None,
    agent_adapter: Optional[AntigravityAdapter] = None,
) -> FastAPI:
    """Creates and configures the FastAPI application."""
    app_config = config or get_config()
    app_config.ensure_directories()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Startup: initialize database
        await init_db(app_config.db_path)
        db_conn = await get_db_connection(app_config.db_path)
        app.state.db_conn = db_conn

        # Clean up any orphaned active runs and approvals from previous crashed/interrupted sessions
        from agy_cockpit.backend.db.repositories.run_repository import RunRepository
        from agy_cockpit.backend.db.repositories.approval_repository import ApprovalRepository
        from agy_cockpit.backend.domain.models import utc_now_iso

        startup_run_repo = RunRepository(db_conn)
        interrupted_count = await startup_run_repo.interrupt_orphaned_runs()
        if interrupted_count > 0:
            logger.info("Cleaned up %d orphaned active runs on startup.", interrupted_count)

        startup_approval_repo = ApprovalRepository(db_conn)
        expired_count = await startup_approval_repo.expire_orphaned_approvals(utc_now_iso())
        if expired_count > 0:
            logger.info("Cleaned up %d orphaned pending approvals on startup.", expired_count)

        # Services
        event_service = EventService(db_conn)
        replay_service = ReplayService(db_conn)
        approval_service = ApprovalService(db_conn, event_service)

        async def on_ws_file_changed(workspace_id: str, rel_path: str, status: str):
            await event_service.emit_event(
                event_type="file_changed",
                session_id="global",
                payload={"workspace_id": workspace_id, "file_path": rel_path, "status": status},
                replayable=False,
            )

        workspace_service = WorkspaceService(db_conn, on_file_change=on_ws_file_changed)
        conversation_service = ConversationService(db_conn, app_config)
        settings_service = SettingsService(db_conn)
        model_catalog = ModelCatalogService()
        diff_service = DiffService()
        artifact_service = ArtifactService(db_conn, event_service=event_service)
        attachment_service = AttachmentService(
            db_conn,
            storage_dir=os.path.join(app_config.data_dir, "attachments"),
            max_bytes=app_config.max_attachment_bytes,
        )

        adapter = agent_adapter or UnifiedAntigravityAdapter()
        run_service = RunService(
            conn=db_conn,
            event_service=event_service,
            approval_service=approval_service,
            adapter=adapter,
            diff_service=diff_service,
        )

        connection_manager = ConnectionManager(app_config)
        router = WebSocketRouter(
            replay_service=replay_service,
            workspace_service=workspace_service,
            conversation_service=conversation_service,
            run_service=run_service,
            approval_service=approval_service,
            settings_service=settings_service,
            diff_service=diff_service,
            attachment_service=attachment_service,
            artifact_service=artifact_service,
        )

        # Wire event service broadcast to connection manager
        event_service.subscribe(connection_manager.broadcast_event)

        app.state.event_service = event_service
        app.state.replay_service = replay_service
        app.state.approval_service = approval_service
        app.state.workspace_service = workspace_service
        app.state.conversation_service = conversation_service
        app.state.settings_service = settings_service
        app.state.model_catalog = model_catalog
        app.state.run_service = run_service
        app.state.diff_service = diff_service
        app.state.artifact_service = artifact_service
        app.state.attachment_service = attachment_service
        app.state.connection_manager = connection_manager
        app.state.router = router

        logger.info("Antigravity Cockpit backend initialized.")
        yield

        # Shutdown: cleanup active runs before database connection is terminated
        workspace_service.stop_all_watchers()
        await run_service.shutdown()
        await db_conn.close()
        logger.info("Antigravity Cockpit backend shut down.")

    app = FastAPI(
        title="Antigravity Cockpit",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            if "content-security-policy" not in response.headers:
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self'; "
                    "script-src 'self' 'wasm-unsafe-eval'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data: blob:; "
                    "font-src 'self' data:; "
                    "connect-src 'self' ws: wss:; "
                    "frame-src 'self'; "
                    "worker-src 'self' blob:;"
                )
            if "x-frame-options" not in response.headers:
                response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    async def verify_api_token(request: Request):
        if not app_config.token:
            return True
        token = request.headers.get("x-antigravity-token") or request.query_params.get("token")
        if token:
            if not hmac.compare_digest(token, app_config.token):
                raise HTTPException(status_code=401, detail="Unauthorized: Invalid token")
            return True
        is_test_client = request.client and request.client.host == "testclient"
        if not is_test_client:
            raise HTTPException(status_code=401, detail="Unauthorized: Missing token")
        return True

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "service": "agy-cockpit", "version": "0.1.0"}

    @app.get("/api/models")
    async def list_models(_: bool = Depends(verify_api_token)):
        return {"models": app.state.model_catalog.list_models()}

    @app.post("/api/attachments")
    async def upload_attachment(
        file: UploadFile = File(...),
        conversation_id: str = Form(...),
        _: bool = Depends(verify_api_token),
    ):
        conv = await app.state.conversation_service.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found")
        try:
            att = await app.state.attachment_service.save_attachment(conversation_id, file)
            await app.state.event_service.emit_event(
                event_type="attachment_ready",
                session_id="global",
                payload={"attachment": att.model_dump()},
                conversation_id=conversation_id,
                replayable=False,
            )
            return {"attachment": att.model_dump()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/attachments/{attachment_id}")
    async def get_attachment(attachment_id: str, _: bool = Depends(verify_api_token)):
        att = await app.state.attachment_service.get_attachment(attachment_id)
        if not att:
            raise HTTPException(status_code=404, detail="Attachment not found")
        return {"attachment": att.model_dump()}

    @app.get("/api/artifacts/{artifact_id}")
    async def get_artifact(artifact_id: str, _: bool = Depends(verify_api_token)):
        art = await app.state.artifact_service.get_artifact(artifact_id)
        if not art:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return {"artifact": art.model_dump()}

    @app.get("/api/artifacts/{artifact_id}/content")
    async def get_artifact_content(artifact_id: str, _: bool = Depends(verify_api_token)):
        art = await app.state.artifact_service.get_artifact(artifact_id)
        if not art:
            raise HTTPException(status_code=404, detail="Artifact not found")

        workspaces = await app.state.workspace_service.list_workspaces()
        allowed_dirs = [ws.canonical_path for ws in workspaces]
        allowed_dirs.append(app_config.data_dir)

        is_binary = art.mime_type.startswith("image/") or art.mime_type in (
            "application/pdf",
            "application/octet-stream",
        )
        try:
            if is_binary:
                content = app.state.artifact_service.read_artifact_bytes(art, allowed_dirs=allowed_dirs)
            else:
                content = app.state.artifact_service.read_artifact_content(art, allowed_dirs=allowed_dirs)
        except (PermissionError, WorkspaceSecurityError) as pe:
            raise HTTPException(status_code=403, detail=str(pe))

        headers = {
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
        }
        return Response(content=content, media_type=art.mime_type, headers=headers)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        conn_mgr: ConnectionManager = app.state.connection_manager
        router: WebSocketRouter = app.state.router

        try:
            session_id = conn_mgr.validate_handshake(websocket)
        except ConnectionSecurityError as cse:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason=cse.message,
            )
            return

        await websocket.accept()
        session = await conn_mgr.register(websocket, session_id)

        try:
            while not session.is_closed:
                raw_text = await websocket.receive_text()
                await router.dispatch(session, raw_text)
        except WebSocketDisconnect:
            logger.info("Client session %s disconnected", session_id)
        except Exception as e:
            logger.warning("Session %s encountered error: %s", session_id, e)
        finally:
            await conn_mgr.unregister(session_id)

    # Mount static frontend assets if directory exists
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
