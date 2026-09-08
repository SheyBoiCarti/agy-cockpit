"""Command Line Interface (CLI) for Antigravity Cockpit (`agy-cockpit`)."""

import argparse
import os
import pathlib
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import List, Optional

import uvicorn

from agy_cockpit import __version__
from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig, set_config

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parses command-line arguments for agy-cockpit."""
    parser = argparse.ArgumentParser(
        prog="agy-cockpit",
        description="Antigravity Cockpit — Local-first control plane for Google Antigravity agents.",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        type=str,
        default=None,
        help="Path to workspace directory (default: None, opens workspace picker).",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8080,
        help="Port to listen on (default: 8080).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind to (loopback only, default: 127.0.0.1).",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="~/.agy-cockpit",
        help="Directory to store sqlite db, logs, attachments, and sessions (default: ~/.agy-cockpit).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        default=False,
        help="Do not automatically open the web cockpit in the browser.",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Explicit launch token for session authentication (default: randomly generated).",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"agy-cockpit {__version__}",
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> AppConfig:
    """Validates parameters and builds AppConfig."""
    if args.host not in LOOPBACK_HOSTS:
        sys.stderr.write(
            f"Security Error: Host '{args.host}' is not a permitted loopback interface.\n"
            f"agy-cockpit v1 strictly enforces loopback-only binding ({', '.join(sorted(LOOPBACK_HOSTS))}) "
            "for local control plane security.\n"
        )
        sys.exit(1)

    data_dir = str(pathlib.Path(args.data_dir).expanduser().resolve())
    token = args.token or secrets.token_hex(24)

    allowed_origins = [
        f"http://{args.host}:{args.port}",
        f"http://127.0.0.1:{args.port}",
        f"http://localhost:{args.port}",
        "http://localhost:5173",  # Dev vite server
        "http://127.0.0.1:5173",
    ]

    cfg = AppConfig(
        host=args.host,
        port=args.port,
        data_dir=data_dir,
        token=token,
        allowed_origins=allowed_origins,
    )
    cfg.ensure_directories()
    set_config(cfg)
    return cfg


def main(argv: Optional[List[str]] = None) -> None:
    """Main CLI entry point for agy-cockpit."""
    args = parse_args(argv)
    cfg = build_config(args)

    workspace_canonical: Optional[str] = None
    if args.workspace:
        ws_path = pathlib.Path(args.workspace).expanduser().resolve()
        if not ws_path.exists() or not ws_path.is_dir():
            sys.stderr.write(f"Error: Specified workspace path does not exist or is not a directory: {ws_path}\n")
            sys.exit(1)
        workspace_canonical = str(ws_path)

    # Construct launch URL
    query_params = {"token": cfg.token}
    if workspace_canonical:
        query_params["workspace"] = workspace_canonical
    launch_url = f"http://{cfg.host}:{cfg.port}/?{urllib.parse.urlencode(query_params)}"

    print("=" * 64)
    print(f" Antigravity Cockpit (agy-cockpit) v{__version__}")
    print("=" * 64)
    print(f" Binding interface : {cfg.host}:{cfg.port}")
    print(f" Session Token     : {cfg.token}")
    print(f" Data Directory    : {cfg.data_dir}")
    if workspace_canonical:
        print(f" Initial Workspace : {workspace_canonical}")
    print(f" Cockpit URL       : {launch_url}")
    print("=" * 64)

    if not args.no_open:
        def _open():
            time.sleep(0.75)
            try:
                webbrowser.open(launch_url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
