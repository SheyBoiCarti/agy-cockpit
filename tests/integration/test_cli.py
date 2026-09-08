"""Tests for the agy-cockpit CLI entry point."""

import subprocess
import sys
import pytest

from agy_cockpit import __version__
from agy_cockpit.cli import build_config, parse_args


def test_cli_args_parsing_defaults():
    """Validates default argument parsing."""
    args = parse_args([])
    assert args.port == 8080
    assert args.host == "127.0.0.1"
    assert args.workspace is None
    assert args.no_open is False
    assert args.token is None
    assert args.data_dir == "~/.agy-cockpit"


def test_cli_args_custom(tmp_path):
    """Validates custom argument values."""
    custom_dir = str(tmp_path / "custom_data")
    custom_ws = str(tmp_path / "workspace")
    args = parse_args([
        "--workspace", custom_ws,
        "--port", "9090",
        "--host", "localhost",
        "--data-dir", custom_dir,
        "--no-open",
        "--token", "secret-test-token-123",
    ])
    assert args.workspace == custom_ws
    assert args.port == 9090
    assert args.host == "localhost"
    assert args.data_dir == custom_dir
    assert args.no_open is True
    assert args.token == "secret-test-token-123"


def test_cli_build_config_loopback(tmp_path):
    """Validates AppConfig generation and directory creation for permitted loopback hosts."""
    custom_dir = str(tmp_path / "cockpit_data")
    args = parse_args([
        "--port", "8888",
        "--host", "127.0.0.1",
        "--data-dir", custom_dir,
        "--token", "custom-token-xyz",
    ])
    cfg = build_config(args)
    assert cfg.port == 8888
    assert cfg.host == "127.0.0.1"
    assert cfg.token == "custom-token-xyz"
    assert "http://127.0.0.1:8888" in cfg.allowed_origins
    assert tmp_path.joinpath("cockpit_data").exists()


def test_cli_build_config_rejects_non_loopback(tmp_path):
    """Validates rejection of non-loopback host binding."""
    args = parse_args([
        "--host", "0.0.0.0",
        "--data-dir", str(tmp_path),
    ])
    with pytest.raises(SystemExit) as exc_info:
        build_config(args)
    assert exc_info.value.code == 1


def test_cli_subprocess_version():
    """Runs agy-cockpit --version as external process."""
    res = subprocess.run(
        [sys.executable, "-m", "agy_cockpit.cli", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"agy-cockpit {__version__}" in res.stdout


def test_cli_subprocess_help():
    """Runs agy-cockpit --help as external process."""
    res = subprocess.run(
        [sys.executable, "-m", "agy_cockpit.cli", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Antigravity Cockpit" in res.stdout
    assert "--workspace" in res.stdout
    assert "--port" in res.stdout
    assert "--no-open" in res.stdout
