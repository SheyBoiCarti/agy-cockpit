"""Exercise real worker lifecycle; deliberately outside COUNCIL_TEST_MODE tests."""
import asyncio
import json
import sys
import pytest
from agy_cockpit.council.member import CouncilMember
from agy_cockpit.council.personas import ARCHITECT_PERSONA


def fake_worker(monkeypatch, script):
    monkeypatch.delenv('COUNCIL_TEST_MODE', raising=False)
    monkeypatch.setattr('shutil.which', lambda _: sys.executable)
    spawn = asyncio.create_subprocess_exec
    workers = []
    async def start(*args, **kwargs):
        process = await spawn(sys.executable, '-c', script, stdout=kwargs['stdout'], stderr=kwargs['stderr'], **({k: kwargs[k] for k in ('creationflags', 'start_new_session') if k in kwargs}))
        workers.append(process)
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', start)
    return workers


@pytest.mark.asyncio
async def test_council_cancel_stops_owned_workers(monkeypatch):
    workers = fake_worker(monkeypatch, 'import time; time.sleep(60)')
    member = CouncilMember(ARCHITECT_PERSONA)
    cancel = asyncio.Event()
    task = asyncio.create_task(member.chat('question', cancellation_token=cancel))
    while not workers:
        await asyncio.sleep(.01)
    cancel.set()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert workers[0].returncode is not None
    finally:
        for worker in workers:
            if worker.returncode is None: worker.kill(); await worker.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize('script', ['import sys; sys.stderr.write("failed"); sys.exit(4)', 'print("not-json")'])
async def test_council_worker_failure_is_not_a_vote(monkeypatch, script):
    fake_worker(monkeypatch, script)
    member = CouncilMember(ARCHITECT_PERSONA)
    with pytest.raises(Exception, match='failed|empty|result|exited'):
        await member.chat('question')


@pytest.mark.asyncio
async def test_council_timeout_reaps_worker(monkeypatch):
    workers = fake_worker(monkeypatch, 'import time; time.sleep(60)')
    member = CouncilMember(ARCHITECT_PERSONA, member_timeout_seconds=.1)
    with pytest.raises(Exception, match='timed out'):
        await member.chat('question')
    assert workers[0].returncode is not None


@pytest.mark.asyncio
async def test_council_roster_and_progress():
    from agy_cockpit.council.council import AICouncil
    events = []
    async def runner(member, prompt, token, thought, cancel):
        await token('a real attributed delta')
        return 'Independent assessment'
    council = AICouncil(runner=runner, on_progress=lambda *args: events.append(args))
    result = await council.deliberate('Separate conversation drafts')
    assert len(result.stage_1_perspectives) == 3
    assert len(result.stage_2_critiques) == 3
    assert {e[0] for e in events} == {'analysis', 'critique', 'synthesis'}
    assert len([e for e in events if e[2] == 'completed']) == 7
    assert all(e[1] in {m.id for m in [*council.members, council.chair]} for e in events)


@pytest.mark.asyncio
async def test_council_vote_result_integrity():
    from agy_cockpit.council.council import AICouncil
    async def runner(member, prompt, *args):
        assert member.title in prompt
        return {'architect': '**APPROVE**: Good.', 'security': 'REJECT Risk.', 'pragmatist': 'ABSTAIN Unsure.'}[member.id]
    council = AICouncil(runner=runner)
    result = await council.vote('Motion')
    assert result['outcome'] == 'TIED'
    assert result['tally'] == {'APPROVE': 1, 'REJECT': 1, 'ABSTAIN': 1}
    async def invalid(*args): return 'Error: model unavailable'
    council = AICouncil(runner=invalid)
    with pytest.raises(Exception, match='malformed vote'):
        await council.vote('Motion')


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['STAGE 1', 'STAGE 2', 'STAGE 3', 'VOTE'])
async def test_council_cancellation_prevents_later_stages(stage):
    from agy_cockpit.council.council import AICouncil
    started = asyncio.Event()
    cancel = asyncio.Event()
    calls = []
    async def runner(member, prompt, token, thought, cancellation):
        calls.append(prompt)
        if stage in prompt:
            started.set()
            await cancellation.wait()
            raise asyncio.CancelledError()
        return 'Assessment'
    council = AICouncil(runner=runner)
    task = asyncio.create_task(council.vote('Separate drafts', cancellation_token=cancel) if stage == 'VOTE' else council.deliberate('Separate drafts', cancellation_token=cancel))
    await asyncio.wait_for(started.wait(), 3)
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    if stage != 'STAGE 3':
        assert not any('STAGE 3' in prompt for prompt in calls)


@pytest.mark.asyncio
async def test_council_large_stderr_does_not_deadlock(monkeypatch):
    fake_worker(monkeypatch, 'import sys,json; sys.stderr.write("x"*1048576); print(json.dumps({"event":"result","result":{"response":"A complete answer"}}))')
    member = CouncilMember(ARCHITECT_PERSONA, member_timeout_seconds=5)
    assert await member.chat('question') == 'A complete answer'


@pytest.mark.asyncio
async def test_missing_cli_never_fabricates_council_success(monkeypatch):
    monkeypatch.delenv('COUNCIL_TEST_MODE', raising=False)
    monkeypatch.setattr('shutil.which', lambda _: None)
    with pytest.raises(Exception, match='CLI is missing'):
        await CouncilMember(ARCHITECT_PERSONA).chat('question')


@pytest.fixture
async def runtime_services(db_conn, tmp_path):
    from agy_cockpit.backend.domain.models import Workspace, Conversation
    from agy_cockpit.backend.db.repositories import WorkspaceRepository, ConversationRepository
    from agy_cockpit.backend.services.event_service import EventService
    from agy_cockpit.backend.services.approval_service import ApprovalService
    from agy_cockpit.backend.services.run_service import RunService
    from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
    workspace = Workspace(canonical_path=str(tmp_path), display_name='workspace')
    await WorkspaceRepository(db_conn).create(workspace)
    conversation = Conversation(workspace_id=workspace.id, title='Runtime tests')
    await ConversationRepository(db_conn).create(conversation)
    events = EventService(db_conn)
    approvals = ApprovalService(db_conn, events)
    service = RunService(db_conn, events, approvals, adapter=MockAntigravityAdapter(tools=[{'id': 'sdk-tool', 'name': 'list_directory', 'args': {}}]))
    yield service, approvals, events, conversation
    await service.shutdown()


@pytest.mark.asyncio
async def test_tool_ids_are_scoped_to_run(runtime_services):
    service, _, _, conversation = runtime_services
    runs = []
    for _ in range(2):
        run = await service.start_prompt_run('session', conversation.id, 'List files')
        await asyncio.wait_for(service._active_runs[run.id].task, 5)
        assert (await service.run_repo.get_by_id(run.id)).state.value == 'completed'
        runs.append(run)
    tools = [await service.tool_repo.list_by_run(run.id) for run in runs]
    assert len(tools[0]) == len(tools[1]) == 1
    assert tools[0][0].id != tools[1][0].id


@pytest.mark.asyncio
async def test_unknown_council_member_is_rejected_before_run(runtime_services):
    service, _, _, conversation = runtime_services
    with pytest.raises(ValueError, match='Unknown Council member'):
        await service.start_prompt_run('session', conversation.id, 'question', council_action={'kind': 'ask', 'member_id': 'not-a-member'})
    assert not service._active_runs


@pytest.mark.asyncio
async def test_council_approval_reject_and_cancel(runtime_services, tmp_path):
    from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
    service, approvals, events, conversation = runtime_services
    service.adapter = MockAntigravityAdapter(tools=[{'id': 'write', 'name': 'create_file', 'args': {'file_path': 'must-not-exist.txt'}, 'requires_approval': True}])
    received = []
    ready = asyncio.Event()
    async def listen(event):
        received.append(event)
        if event.type == 'approval_required': ready.set()
    events.subscribe(listen)
    run = await service.start_prompt_run('session', conversation.id, 'Test policy', council_action={'kind': 'ask', 'member_id': 'architect'})
    await asyncio.wait_for(ready.wait(), 3)
    await service.cancel_run(run.id)
    await asyncio.wait_for(service._active_runs[run.id].task, 5)
    assert not (tmp_path / 'must-not-exist.txt').exists()
    assert len([e for e in received if e.type == 'run_cancelled']) == 1
    assert not [e for e in received if e.type == 'run_completed']


@pytest.mark.asyncio
async def test_sdk_council_rejection_without_tool_id(runtime_services, tmp_path):
    from google import antigravity as agy
    from agy_cockpit.backend.services.agent_service import TurnResult
    from agy_cockpit.backend.domain.enums import RunState, ApprovalDecision
    service, approvals, events, conversation = runtime_services
    ready = asyncio.Event()
    requests = []
    async def listen(event):
        if event.type == 'approval_required': requests.append(event); ready.set()
    events.subscribe(listen)
    class SDKShapeAdapter:
        async def run_turn(self, **kwargs):
            allowed = await kwargs['approval_handler'](agy.types.ToolCall(name='create_file', args={'file_path': 'denied.txt'}))
            if allowed: (tmp_path / 'denied.txt').write_text('should not be written')
            return TurnResult(final_text='Allowed' if allowed else 'Rejected safely', reasoning_text='', state=RunState.COMPLETED)
    service.adapter = SDKShapeAdapter()
    run = await service.start_prompt_run('session', conversation.id, 'Test SDK policy', council_action={'kind': 'ask', 'member_id': 'architect'})
    task = service._active_runs[run.id].task
    await asyncio.wait_for(ready.wait(), 3)
    assert requests[0].payload['tool_execution_id'] is None
    await approvals.resolve_approval(requests[0].payload['approval_request_id'], ApprovalDecision.REJECTED)
    await asyncio.wait_for(task, 5)
    assert not (tmp_path / 'denied.txt').exists()
    assert (await service.run_repo.get_by_id(run.id)).state == RunState.COMPLETED


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='Windows descendant ownership regression')
async def test_worker_job_reaps_child_after_parent_exits():
    import ctypes
    from ctypes import wintypes
    from agy_cockpit.backend.services.process_utils import spawn_owned_process, terminate_process_tree
    script = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True)"
    process = await spawn_owned_process(sys.executable, '-c', script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    handle = None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        child_pid = int(await asyncio.wait_for(process.stdout.readline(), 3))
        handle = kernel.OpenProcess(0x100000, False, child_pid)
        assert handle
        for _ in range(100):
            if process.returncode is not None: break
            await asyncio.sleep(.01)
        assert process.returncode is not None
        await terminate_process_tree(process)
        assert kernel.WaitForSingleObject(handle, 3000) == 0
    finally:
        await terminate_process_tree(process)
        if handle: kernel.CloseHandle(handle)
