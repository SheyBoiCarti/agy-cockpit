"""The CLI hook must wait for a decision before the worker can mutate a file."""
import asyncio
import json
import os
import sys

import pytest

from agy_cockpit.backend.services.cli_permission_bridge import CLIPermissionBridge


async def noop(*args):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize('decision', ['approve', 'reject', 'cancel'])
async def test_hook_gates_real_worker_side_effect(tmp_path, decision):
    target = tmp_path / 'protected.txt'
    target.write_text('ORIGINAL')
    asked, release = asyncio.Event(), asyncio.Event()
    cancel = asyncio.Event()
    calls = []

    async def approve(tool):
        calls.append(tool)
        asked.set()
        await release.wait()
        return decision == 'approve'

    async with CLIPermissionBridge(str(tmp_path), 'request-review', cancel, approve, noop, noop) as gate:
        # The actual standalone hook runs in a separate process, as it does in agy.
        async def hook(phase, payload):
            proc = await asyncio.create_subprocess_exec(sys.executable, str(gate.hook_path), phase,
                env={**os.environ, **gate.environment}, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate(json.dumps(payload).encode())
            assert proc.returncode == 0, err.decode()
            return json.loads(out)

        assert await hook('preflight', {}) == {'injectSteps': []}

        async def worker():
            result = await hook('tool', {'stepIdx': 4, 'toolCall': {'name': 'replace_file_content',
                'args': {'TargetFile': str(target), 'ReplacementContent': 'CHANGED'}}})
            if result['decision'] == 'allow':
                target.write_text('CHANGED')
            return result

        task = asyncio.create_task(worker())
        await asyncio.wait_for(asked.wait(), 5)
        await asyncio.sleep(.2)
        assert target.read_text() == 'ORIGINAL'
        assert calls[0].args['ReplacementContent'] == 'CHANGED'
        if decision == 'cancel':
            cancel.set()
        else:
            release.set()
        result = await asyncio.wait_for(task, 5)
        assert result['decision'] == ('allow' if decision == 'approve' else 'deny')
        assert target.read_text() == ('CHANGED' if decision == 'approve' else 'ORIGINAL')
    assert not gate.root.exists()


@pytest.mark.asyncio
async def test_unknown_tools_require_approval_and_hook_failure_denies(tmp_path):
    cancel = asyncio.Event()
    seen = []

    async def approve(tool):
        seen.append(tool.name)
        return False

    async with CLIPermissionBridge(str(tmp_path), 'request-review', cancel, approve, noop, noop) as gate:
        await gate.decide({'stepIdx': 0, 'toolCall': {'name': 'future_modifying_tool', 'args': {}}})
        assert seen == ['future_modifying_tool']
        assert cancel.is_set()
        proc = await asyncio.create_subprocess_exec(sys.executable, str(gate.hook_path), 'tool',
            env={**os.environ, 'AGY_COCKPIT_GATE_DIR': ''}, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)
        out, _ = await proc.communicate(b'{}')
        assert json.loads(out)['decision'] == 'deny'


@pytest.mark.asyncio
async def test_read_tools_do_not_request_modification_approval(tmp_path):
    async def unexpected(tool):
        pytest.fail(f'Read tool prompted: {tool.name}')

    async with CLIPermissionBridge(str(tmp_path), 'strict', asyncio.Event(), unexpected, noop, noop) as gate:
        result = await gate.decide({'stepIdx': 1, 'toolCall': {'name': 'view_file', 'args': {'AbsolutePath': 'file.txt'}}})
        assert result['decision'] == 'allow'


@pytest.mark.asyncio
async def test_unsupported_cli_cannot_mutate_before_reporting_active(tmp_path):
    from agy_cockpit.backend.services.agent_service import CLISubscriptionAdapter
    target = tmp_path / 'victim.txt'
    target.write_text('ORIGINAL')
    worker = tmp_path / 'unsupported.py'
    worker.write_text('from pathlib import Path\nimport json\n'
        f'Path({str(target)!r}).write_text("CHANGED")\n'
        'print(json.dumps({"event":"step_update","step_update":{"step_type":"tool","state":"ACTIVE","tool_name":"edit_file"}}),flush=True)\n')
    adapter = CLISubscriptionAdapter(sys.executable)
    adapter._build_cmd = lambda *a, **kw: [sys.executable, str(worker)]
    result = await adapter.run_turn(conversation_id='unsupported', save_dir=str(tmp_path),
        workspace_path=str(tmp_path), prompt='edit', model_slug='test', policy_preset='request-review',
        approval_handler=noop, on_thought=noop, on_token=noop, on_tool_start=noop,
        on_tool_finish=noop, cancellation_token=asyncio.Event())
    assert target.read_text() == 'ORIGINAL'
    assert result.state.value == 'failed'


@pytest.mark.asyncio
async def test_cancel_finishes_hook_tool_without_active_telemetry(tmp_path, monkeypatch):
    import agy_cockpit.backend.services.agent_service as service
    # This controlled worker implements the native hook contract but emits no
    # tool ACTIVE telemetry. A verified CLI cannot rely on stdout for cleanup.
    monkeypatch.setattr(service, 'verify_cli_hook_support', noop, raising=False)
    worker = tmp_path / 'hook_worker.py'
    worker.write_text('import subprocess,sys,json\n'
        'hook=".agents/cockpit_permission_hook.py"\n'
        'subprocess.run([sys.executable,hook,"preflight"],input=b"{}",stdout=subprocess.PIPE)\n'
        'subprocess.run([sys.executable,hook,"tool"],input=json.dumps({"stepIdx":1,"toolCall":{"name":"edit_file","args":{"path":"file.txt"}}}).encode(),stdout=subprocess.PIPE)\n')
    adapter = service.CLISubscriptionAdapter(sys.executable)
    adapter._build_cmd = lambda *a, **kw: [sys.executable, str(worker)]
    asked, cancel = asyncio.Event(), asyncio.Event()
    finished = []
    async def approve(tool):
        asked.set()
        await asyncio.Event().wait()
    async def finish(*args):
        finished.append(args)
    task = asyncio.create_task(adapter.run_turn(conversation_id='hook-worker', save_dir=str(tmp_path),
        workspace_path=str(tmp_path), prompt='edit', model_slug='test', policy_preset='strict',
        approval_handler=approve, on_thought=noop, on_token=noop, on_tool_start=noop,
        on_tool_finish=finish, cancellation_token=cancel))
    await asyncio.wait_for(asked.wait(), 5)
    cancel.set()
    result = await asyncio.wait_for(task, 5)
    assert result.state.value == 'cancelled'
    assert len(finished) == 1
    assert finished[0][0] == 'tool-1-edit_file'
    assert finished[0][2] is False


@pytest.mark.asyncio
async def test_hook_setup_failure_preserves_error_and_cleans_up(tmp_path, monkeypatch):
    import agy_cockpit.backend.services.agent_service as service
    import agy_cockpit.backend.services.cli_permission_bridge as bridge
    monkeypatch.setattr(service, 'verify_cli_hook_support', noop)
    def failed_copy(*args):
        raise OSError('Hook installation unavailable')
    monkeypatch.setattr(bridge.shutil, 'copyfile', failed_copy)
    result = await service.CLISubscriptionAdapter(sys.executable).run_turn(
        conversation_id='setup-error', save_dir=str(tmp_path), workspace_path=str(tmp_path),
        prompt='edit', model_slug='test', policy_preset='strict', approval_handler=noop,
        on_thought=noop, on_token=noop, on_tool_start=noop, on_tool_finish=noop,
        cancellation_token=asyncio.Event())
    assert result.state.value == 'failed'
    assert result.error_message == 'Hook installation unavailable'
    assert not list(tmp_path.glob('.agy-cockpit-*'))
