"""Connect the CLI's synchronous PreToolUse hook to Cockpit approvals."""
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import weakref

from agy_cockpit.backend.services.process_utils import spawn_owned_process, terminate_process_tree

logger = logging.getLogger(__name__)

# Everything else, including future tools and MCP calls, needs a decision.
READ_TOOLS = frozenset({'view_file', 'list_dir', 'grep_search', 'find_by_name',
    'search_web', 'read_url_content', 'list_resources', 'read_resource',
    'list_permissions', 'command_status', 'wait', 'wait_5_seconds'})

_verified_binaries = set()
_verification_locks = weakref.WeakKeyDictionary()


async def verify_cli_hook_support(executable, model_slug, cancellation):
    """Prove native denial in disposable data BEFORE launching a workspace turn.

    stdout readiness checks alone cannot protect against an older CLI ignoring
    hooks. Cache successful safety checks for this executable's file identity.
    """
    binary = Path(shutil.which(executable) or executable).resolve()
    stat = binary.stat()
    identity = (str(binary), stat.st_size, stat.st_mtime_ns, stat.st_ino)
    lock = _verification_locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())
    # Stop also works while another Council member owns the safety check.
    acquire = asyncio.create_task(lock.acquire())
    cancelled = asyncio.create_task(cancellation.wait())
    try:
        done, _ = await asyncio.wait({acquire, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        if cancelled in done:
            raise asyncio.CancelledError()
        if identity in _verified_binaries:
            return
        await _probe_hook_denial(str(binary), model_slug, cancellation)
        current = binary.stat()
        if identity[1:] != (current.st_size, current.st_mtime_ns, current.st_ino):
            raise RuntimeError('CLI changed during permission verification; retry the request.')
        _verified_binaries.add(identity)
    finally:
        acquire.cancel()
        cancelled.cancel()
        await asyncio.gather(acquire, cancelled, return_exceptions=True)
        if acquire.done() and not acquire.cancelled() and acquire.result():
            lock.release()


async def _probe_hook_denial(executable, model_slug, cancellation):
    async def reject(tool):
        return False
    async def noop(*args):
        pass
    with tempfile.TemporaryDirectory(prefix='agy-cockpit-permission-check-') as workspace:
        target = Path(workspace) / 'permission-check.txt'
        target.write_text('ORIGINAL', encoding='utf-8')
        async with CLIPermissionBridge(workspace, 'strict', cancellation, reject, noop, noop,
                                       cancel_on_rejection=False) as gate:
            prompt = (f'Permission integration check. Use write_to_file or replace_file_content to '
                f'overwrite {target.as_posix()} with exactly CHANGED. Actually call the editing tool; '
                'do not just describe it. Do not edit other files. If the tool is denied, stop immediately.')
            proc = await spawn_owned_process(executable, '--print', prompt, '--output-format', 'stream-json',
                '--add-dir', workspace, '--model', model_slug, cwd=str(gate.root),
                env={**os.environ, **gate.environment}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            output = asyncio.create_task(proc.communicate())
            stopped = asyncio.create_task(cancellation.wait())
            try:
                done, _ = await asyncio.wait({output, stopped}, timeout=60, return_when=asyncio.FIRST_COMPLETED)
                if stopped in done:
                    raise asyncio.CancelledError()
                if output not in done:
                    raise RuntimeError('CLI permission safety check timed out; no workspace turn launched.')
                stdout, _ = await output
                native_denial = False
                for line in stdout.decode(errors='replace').splitlines():
                    try:
                        step = json.loads(line).get('step_update', {})
                        error = step.get('tool_info', {}).get('error', {})
                        if (step.get('step_type') == 'tool' and step.get('state') == 'ERROR'
                                and 'denied by pre-tool hook' in error.get('message', '')):
                            native_denial = True
                    except (ValueError, AttributeError):
                        continue
                if not (proc.returncode == 0 and gate.ready and gate.rejected and native_denial
                        and target.read_text(encoding='utf-8') == 'ORIGINAL'):
                    raise RuntimeError('CLI permission hook did not initialize or failed its safety check; '
                        'no workspace turn launched. Check CLI login, model access, and hook support.')
            finally:
                await terminate_process_tree(proc)
                output.cancel()
                stopped.cancel()
                await asyncio.gather(output, stopped, return_exceptions=True)


class CLIPermissionBridge:
    def __init__(self, workspace_path, preset, cancellation, approval_handler, on_tool_start, on_tool_finish,
                 cancel_on_rejection=True):
        self.workspace_path = workspace_path
        self.preset = preset
        self.cancellation = cancellation
        self.approval_handler = approval_handler
        self.on_tool_start = on_tool_start
        self.on_tool_finish = on_tool_finish
        self.started_tools = {}
        self.ready = False
        self.rejected = False
        self.cancel_on_rejection = cancel_on_rejection
        self._tasks = set()

    async def __aenter__(self):
        # A child cwd lets native discovery load this hook and ancestor customizations,
        # without changing the user's hooks.json or subscription settings.
        self._temporary = tempfile.TemporaryDirectory(prefix='.agy-cockpit-', dir=self.workspace_path)
        self.root = Path(self._temporary.name)
        customizations = self.root / '.agents'
        customizations.mkdir()
        self.hook_path = customizations / 'cockpit_permission_hook.py'
        shutil.copyfile(Path(__file__).with_name('cli_permission_hook.py'), self.hook_path)
        self.spool = self.root / 'decisions'
        self.spool.mkdir()
        python = Path(sys.executable).name
        command = f'{python} cockpit_permission_hook.py'
        config = {'cockpit-permissions': {
            'PreInvocation': [{'command': command + ' preflight', 'timeout': 310}],
            'PreToolUse': [{'matcher': '*', 'hooks': [{'command': command + ' tool', 'timeout': 310}]}],
        }}
        (customizations / 'hooks.json').write_text(json.dumps(config), encoding='utf-8')
        self.environment = {
            'AGY_COCKPIT_GATE_DIR': str(self.spool),
            'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''),
        }
        self._poller = asyncio.create_task(self._poll())
        return self

    async def __aexit__(self, *exc):
        tasks = list(self._tasks)
        poller = getattr(self, '_poller', None)
        if poller:
            tasks.append(poller)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        temporary = getattr(self, '_temporary', None)
        if temporary:
            temporary.cleanup()

    async def _poll(self):
        handled = set()
        while True:
            for path in self.spool.glob('*.request.json'):
                if path.name not in handled:
                    handled.add(path.name)
                    task = asyncio.create_task(self._respond(path))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            await asyncio.sleep(.025)

    async def _respond(self, path):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if payload['phase'] == 'preflight':
                self.ready = True
                result = {'injectSteps': []}
            else:
                result = await self.decide(payload['data'])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('CLI permission hook failed; blocking tool')
            self.cancellation.set()
            result = {'decision': 'deny', 'reason': 'Permission bridge failed; execution blocked.'}
        response = path.with_name(path.name.replace('.request.json', '.response.json'))
        temporary = response.with_suffix('.tmp')
        temporary.write_text(json.dumps(result), encoding='utf-8')
        temporary.replace(response)

    async def decide(self, payload):
        if self.cancellation.is_set():
            return {'decision': 'deny', 'reason': 'Run cancelled.'}
        tool = payload['toolCall']
        name, args, index = tool['name'], tool['args'], payload['stepIdx']
        if not isinstance(name, str) or not isinstance(args, dict) or not isinstance(index, int):
            raise ValueError('Invalid CLI hook tool call')
        tool_id = f'tool-{index}-{name}'
        self.started_tools[tool_id] = {'name': name, 'args': args}
        await self.on_tool_start(tool_id, name, args)
        if name in READ_TOOLS and self.preset != 'always-prompt':
            return {'decision': 'allow'}
        decision = asyncio.create_task(self.approval_handler(SimpleNamespace(id=tool_id, name=name, args=args)))
        cancelled = asyncio.create_task(self.cancellation.wait())
        try:
            done, _ = await asyncio.wait({decision, cancelled}, timeout=290, return_when=asyncio.FIRST_COMPLETED)
            if cancelled in done or self.cancellation.is_set():
                return {'decision': 'deny', 'reason': 'Run cancelled.'}
            approved = decision in done and await decision
            if approved and not self.cancellation.is_set():
                return {'decision': 'allow'}
            self.rejected = True
            await self.on_tool_finish(tool_id, name, False, 'Tool execution rejected before execution')
            self.started_tools.pop(tool_id, None)
            if self.cancel_on_rejection:
                self.cancellation.set()
            return {'decision': 'deny', 'reason': 'User rejected execution or approval expired.'}
        finally:
            decision.cancel()
            cancelled.cancel()
            await asyncio.gather(decision, cancelled, return_exceptions=True)
