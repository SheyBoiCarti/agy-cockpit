"""Behavioral regressions for the exploratory QA findings."""
import os
import asyncio
import json
import pytest
pytest.importorskip("playwright")
from playwright.async_api import async_playwright, expect
from tests.e2e.cockpit_browser_support import cockpit_url


@pytest.fixture
async def cockpit_page(cockpit_url):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**({"executable_path": os.environ["QA_CHROMIUM"]} if os.environ.get("QA_CHROMIUM") else {}))
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.add_init_script("""window.__qaSockets=[]; const Native=window.WebSocket; window.WebSocket=class extends Native { constructor(...args) { super(...args); window.__qaSockets.push(this); } };""")
        await page.goto(cockpit_url)
        await expect(page.get_by_role("button", name="New Conversation", exact=True)).to_be_enabled()
        await page.get_by_role("button", name="New Conversation", exact=True).click()
        await expect(page.locator("textarea")).to_be_enabled()
        yield page
        await browser.close()


async def test_action_errors_are_visible(cockpit_page):
    page = cockpit_page
    await page.get_by_role("button", name="Open Workspace Path").click()
    await page.get_by_placeholder("/home/user/project").fill("C:/nonexistent-qa-workspace-123")
    await page.get_by_role("button", name="Open", exact=True).click()
    await expect(page.get_by_role("alert")).to_contain_text("does not exist")
    await page.get_by_role('button', name='Dismiss error', exact=True).click()
    await page.locator('input[type=file]').set_input_files({'name': 'unsupported.exe', 'mimeType': 'application/octet-stream', 'buffer': b'not-an-executable'})
    await expect(page.get_by_role('alert')).to_contain_text('not supported')
    await page.locator('input[type=file]').set_input_files({'name': 'valid.txt', 'mimeType': 'text/plain', 'buffer': b'valid'})
    await expect(page.get_by_title('valid.txt', exact=True)).to_be_visible()


async def test_attachment_drafts_are_isolated(cockpit_page):
    page = cockpit_page
    await page.locator('input[type="file"]').set_input_files({"name": "hello.txt", "mimeType": "text/plain", "buffer": b"hello"})
    await expect(page.get_by_title("hello.txt", exact=True)).to_be_visible()
    await page.locator("textarea").fill("draft in A")
    await page.get_by_role("button", name="New Conversation", exact=True).click()
    await expect(page.locator('aside').first).to_contain_text("Conversations (2)", ignore_case=True)
    await expect(page.get_by_title("hello.txt", exact=True)).to_have_count(0)
    await expect(page.locator("textarea")).to_have_value("")


async def test_reload_restores_workspace_and_sibling_chats(cockpit_page):
    page = cockpit_page
    await page.get_by_role("button", name="New Conversation", exact=True).click()
    await expect(page.locator("aside").first).to_contain_text("Conversations (2)", ignore_case=True)
    await page.reload()
    await expect(page.locator("aside").first).to_contain_text("Conversations (2)", ignore_case=True)
    await expect(page.get_by_role("button", name="New Conversation", exact=True)).to_be_enabled()


@pytest.mark.parametrize("width", [390, 768, 1024, 1280, 1440])
async def test_rename_does_not_overlap_model_controls(cockpit_page, width):
    page = cockpit_page
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.get_by_role("button", name="Rename conversation", exact=True).click(timeout=3000)
    await page.locator("header input").fill("A long conversation title for the rename regression")
    overlap = await page.evaluate("""() => {
      const a = document.querySelector('header input').getBoundingClientRect();
      return [...document.querySelectorAll('header select')].some(e => {
        const b=e.getBoundingClientRect();
        return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
      });
    }""")
    assert not overlap
    await page.get_by_role("button", name="Save conversation name", exact=True).click()
    await expect(page.locator("header h2")).to_have_text("A long conversation title for the rename regression")


async def rename(page, name):
    await page.get_by_role('button', name='Rename conversation', exact=True).click()
    await page.get_by_role('textbox', name='Conversation name', exact=True).fill(name)
    await page.get_by_role('button', name='Save conversation name', exact=True).click()
    await expect(page.locator('header h2')).to_have_text(name)


async def test_upload_finishes_in_originating_chat(cockpit_page):
    page = cockpit_page
    await rename(page, 'Chat A')
    started, release = asyncio.Event(), asyncio.Event()
    async def upload(route):
        started.set()
        await release.wait()
        await route.continue_()
    await page.route('**/api/attachments', upload)
    await page.locator('input[type=file]').set_input_files({'name': 'delayed.txt', 'mimeType': 'text/plain', 'buffer': b'hello'})
    await asyncio.wait_for(started.wait(), 5)
    await page.get_by_role('button', name='New Conversation', exact=True).click()
    await expect(page.locator('header h2')).to_have_text('New Conversation')
    await expect(page.get_by_role('button', name='Add attachment', exact=True)).to_be_enabled()
    release.set()
    await expect(page.get_by_title('delayed.txt', exact=True)).to_have_count(0)
    await page.locator('aside').first.get_by_text('Chat A', exact=True).click()
    await expect(page.get_by_title('delayed.txt', exact=True)).to_be_visible()
    await page.get_by_role('button', name='Remove attachment').click()
    await expect(page.get_by_title('delayed.txt', exact=True)).to_have_count(0)


async def test_rejected_prompt_restores_originating_draft(cockpit_page):
    page = cockpit_page
    await page.route('**/api/attachments', lambda route: route.fulfill(json={'attachment': {'id': 'invalid-other-chat', 'filename': 'file.txt', 'size_bytes': 5}}))
    await page.locator('input[type=file]').set_input_files({'name': 'file.txt', 'mimeType': 'text/plain', 'buffer': b'hello'})
    await expect(page.get_by_title('file.txt', exact=True)).to_be_visible()
    await page.locator('textarea').fill('Keep this rejected prompt')
    await page.get_by_role('button', name='Send', exact=True).click()
    await expect(page.get_by_role('alert')).to_contain_text('does not belong')
    await expect(page.locator('textarea')).to_have_value('Keep this rejected prompt')
    await expect(page.get_by_title('file.txt', exact=True)).to_be_visible()
    await expect(page.get_by_role('button', name='Send', exact=True)).to_be_enabled()


async def test_settings_modal_uses_current_values(cockpit_page):
    page = cockpit_page
    await page.get_by_role('button', name='Settings', exact=True).click()
    await page.get_by_label('Default model', exact=True).select_option('gemini-3.8-flash-low')
    await page.get_by_role('button', name='Save Changes').click()
    await page.get_by_role('button', name='New Conversation', exact=True).click()
    await expect(page.get_by_label('Conversation model', exact=True)).to_have_value('gemini-3.8-flash-low')
    await page.get_by_role('button', name='Settings', exact=True).click()
    await page.get_by_label('Default model', exact=True).select_option('gemini-3.8-flash-high')
    await page.get_by_role('button', name='Cancel', exact=True).click()
    await page.get_by_role('button', name='Settings', exact=True).click()
    await expect(page.get_by_label('Default model', exact=True)).to_have_value('gemini-3.8-flash-low')


@pytest.mark.parametrize('member', ['Architect', 'Security', 'Pragmatist', 'Synthesizer'])
async def test_council_member_question_routing(cockpit_page, member):
    page = cockpit_page
    await page.get_by_role('button', name='Open AI Council Swarm Panel').click()
    await expect(page.get_by_text('3 Council members + 1 synthesis chair')).to_be_visible()
    await page.get_by_role('button', name=f'Ask {member}', exact=True).click()
    await expect(page.get_by_role('button', name='Start Council', exact=True)).to_be_disabled()
    await page.get_by_role('textbox', name='Council question or topic').fill('   ')
    await expect(page.get_by_role('button', name='Start Council', exact=True)).to_be_disabled()
    await page.get_by_role('button', name='Cancel', exact=True).click()
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0)
    await page.get_by_role('button', name=f'Ask {member}', exact=True).click()
    await page.get_by_role('textbox', name='Council question or topic').fill('What is a session boundary?')
    await page.get_by_role('button', name='Start Council', exact=True).click()
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0, timeout=10000)
    await expect(page.locator('main')).to_contain_text(member)
    await expect(page.locator('main')).to_contain_text('Completed response.')
    await expect(page.get_by_text(f'ask · {member.lower()} · completed')).to_be_visible()
    for other in ['architect', 'security', 'pragmatist', 'synthesizer']:
        if other != member.lower():
            await expect(page.get_by_text(f'ask · {other} · completed')).to_have_count(0)


async def test_council_deliberation_vote_and_cancel(cockpit_page):
    page = cockpit_page
    await page.get_by_role('button', name='Open AI Council Swarm Panel').click()
    for button, topic, expected in [('Deliberate', 'Separate drafts', 'Stage 3: Council Synthesis'), ('Roll-Call Vote', 'Use isolated drafts', '3 Approve | 0 Reject | 0 Abstain')]:
        await page.get_by_role('button', name=button, exact=True).click()
        await page.get_by_role('textbox', name='Council question or topic').fill(topic)
        await page.get_by_role('button', name='Start Council', exact=True).click()
        await expect(page.locator('main')).to_contain_text(expected, timeout=15000)
        await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0)
    await page.get_by_role('button', name='Deliberate', exact=True).click()
    await page.get_by_role('textbox', name='Council question or topic').fill('wait-for-cancel')
    await page.get_by_role('button', name='Start Council', exact=True).click()
    await page.get_by_role('button', name='Stop', exact=True).click()
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0, timeout=5000)
    await expect(page.get_by_role('button', name='Deliberate', exact=True)).to_be_enabled()


@pytest.mark.parametrize('reload', [False, True])
async def test_reload_during_run_preserves_output_and_approval(cockpit_page, reload):
    page = cockpit_page
    await page.locator('textarea').fill('reconnect-test approval-test')
    await page.get_by_role('button', name='Send', exact=True).click()
    await expect(page.get_by_role('button', name='Reject', exact=True)).to_be_visible()
    await expect(page.locator('main')).to_contain_text('partial answer')
    if reload:
        await page.reload()
    else:
        await page.evaluate('window.__qaSockets.at(-1).close()')
    await expect(page.get_by_role('button', name='Reject', exact=True)).to_be_visible(timeout=10000)
    # Wait until replacement socket has opened, not merely the old modal remaining visible.
    await page.wait_for_function('() => window.__qaSockets.at(-1)?.readyState === 1')
    await expect(page.locator('main')).to_contain_text('partial answer')
    assert (await page.locator('main').inner_text()).count('partial answer') == 1
    await page.get_by_role('button', name='Reject', exact=True).click()
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0, timeout=5000)


async def test_recovery_clears_finished_offline_run(cockpit_page):
    page = cockpit_page
    await page.evaluate("sessionStorage.setItem('agy_active_run_id', 'finished-offline')")
    await page.reload()
    await expect(page.locator('header h2')).to_have_text('New Conversation')
    await page.locator('textarea').fill('Next turn')
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0)
    await expect(page.get_by_role('button', name='Send', exact=True)).to_be_enabled()


async def test_background_run_events_preserve_selected_controls(cockpit_page):
    page = cockpit_page
    first = await page.evaluate("sessionStorage.getItem('agy_active_conversation_id')")
    await page.get_by_role('button', name='New Conversation', exact=True).click()
    await expect(page.locator('aside').first).to_contain_text('Conversations (2)', ignore_case=True)
    second = await page.evaluate("sessionStorage.getItem('agy_active_conversation_id')")
    async def inject(kind, conversation, run, payload):
        await page.evaluate("""data => window.__qaSockets.at(-1).dispatchEvent(new MessageEvent('message', {data: JSON.stringify(data)}))""", {'type': kind, 'conversation_id': conversation, 'run_id': run, 'event_id': f'{kind}-{run}', 'payload': payload})
    await inject('run_started', first, 'run-a', {'run_id': 'run-a', 'conversation_id': first, 'started_at': '2026-10-19T00:00:00Z', 'user_message_id': 'message-a'})
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0)
    await inject('run_started', second, 'run-b', {'run_id': 'run-b', 'conversation_id': second, 'started_at': '2026-10-19T00:00:00Z', 'user_message_id': 'message-b'})
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_be_visible()

    await inject('approval_required', first, 'run-a', {'approval_request_id': 'approval-a', 'sdk_tool_name': 'run_command', 'args': {}})
    await expect(page.get_by_role('button', name='Reject', exact=True)).to_have_count(0)
    await inject('run_completed', first, 'run-a', {'run_id': 'run-a', 'completed_at': '2026-10-19T00:00:01Z'})
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_be_visible()


@pytest.mark.parametrize('width,height', [(390, 844), (768, 1024), (1440, 1000)])
async def test_responsive_navigation(cockpit_page, width, height):
    page = cockpit_page
    await page.set_viewport_size({'width': width, 'height': height})
    assert await page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')
    assert (await page.locator('textarea').bounding_box())['width'] >= 280
    if width < 768:
        await page.get_by_role('button', name='Open navigation').click()
        await expect(page.get_by_role('button', name='Close navigation')).to_be_visible()
        await page.keyboard.press('Escape')
        await expect(page.get_by_role('button', name='Open navigation')).to_be_focused()
    for title in ['Changed Files & Diffs', 'Command Terminal Output', 'Subagents Tree', 'Generated Artifacts', 'AI Council (Gemini Swarm Deliberation)']:
        await page.locator(f'header button[title="{title}"]').click()
        await expect(page.get_by_role('button', name='Close panel', exact=True)).to_be_visible()
        await page.get_by_role('button', name='Close panel', exact=True).click()
    await page.get_by_role('button', name='Settings', exact=True).click() if width >= 768 else await open_mobile_settings(page)
    await expect(page.get_by_role('dialog', name='Cockpit Settings')).to_be_visible()
    await page.keyboard.press('Escape')
    await expect(page.get_by_role('dialog', name='Cockpit Settings')).to_have_count(0)


async def open_mobile_settings(page):
    await page.get_by_role('button', name='Open navigation').click()
    await page.get_by_role('button', name='Settings', exact=True).click()


async def test_model_options_follow_discovery(cockpit_page):
    page = cockpit_page
    values = await page.get_by_label('Conversation model', exact=True).locator('option').evaluate_all('(es) => es.map(e => e.value)')
    assert 'claude-opus-4-6-thinking' in values
    assert 'gpt-oss-120b-medium' in values
    assert not any('3.7' in v or '3.6' in v or '3.1' in v for v in values)
    await page.locator('textarea').fill('A valid prompt')
    await expect(page.get_by_role('button', name='Send', exact=True)).to_be_enabled()
    await page.route('**/api/models*', lambda route: route.fulfill(json={'models': [], 'status': 'unavailable', 'error': 'Discovery is offline', 'last_success_at': None}))
    await page.get_by_role('button', name='Refresh models', exact=True).click()
    await expect(page.get_by_role('alert')).to_contain_text('Discovery is offline')
    await expect(page.get_by_role('button', name='Send', exact=True)).to_be_disabled()


async def test_rejection_after_switch_keeps_originating_draft(cockpit_page):
    page = cockpit_page
    await rename(page, 'Originating chat')
    await page.evaluate("""() => { const socket=window.__qaSockets.at(-1), original=socket.send.bind(socket); socket.send = data => { const command=JSON.parse(data); if(command.type === 'send_prompt') { window.__heldPrompt=command; return; } original(data); }; }""")
    await page.locator('textarea').fill('Recover this question in A')
    await page.get_by_role('button', name='Send', exact=True).click()
    await page.get_by_role('button', name='New Conversation', exact=True).click()
    await expect(page.locator('header h2')).to_have_text('New Conversation')
    await page.evaluate("""() => { const command=window.__heldPrompt; window.__qaSockets.at(-1).dispatchEvent(new MessageEvent('message', {data: JSON.stringify({type:'protocol_error',event_id:'held-error',conversation_id:command.conversation_id,payload:{request_id:command.request_id,error_code:'INVALID_MESSAGE',message:'Controlled rejected send'}})})); }""")
    await expect(page.locator('textarea')).to_have_value('')
    await page.locator('aside').first.get_by_text('Originating chat', exact=True).click()
    await expect(page.locator('textarea')).to_have_value('Recover this question in A')
    await expect(page.get_by_role('button', name='Send', exact=True)).to_be_enabled()


async def test_acceptance_preserves_newer_draft_edits(cockpit_page):
    page = cockpit_page
    await page.locator('input[type=file]').set_input_files({'name': 'sent.txt', 'mimeType': 'text/plain', 'buffer': b'sent'})
    await expect(page.get_by_title('sent.txt', exact=True)).to_be_visible()
    await page.evaluate("""() => { const socket=window.__qaSockets.at(-1), original=socket.send.bind(socket); socket.send = data => { const command=JSON.parse(data); if(command.type === 'send_prompt') { window.__heldPrompt=command; return; } original(data); }; }""")
    await page.locator('textarea').fill('Original draft')
    await page.get_by_role('button', name='Send', exact=True).click()
    await page.locator('textarea').fill('Newer draft')
    await page.locator('input[type=file]').set_input_files({'name': 'newer.txt', 'mimeType': 'text/plain', 'buffer': b'new'})
    await expect(page.get_by_title('newer.txt', exact=True)).to_be_visible()

    await page.evaluate("""() => { const c=window.__heldPrompt; window.__qaSockets.at(-1).dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'run_started',event_id:'accepted-held',run_id:'accepted-run',conversation_id:c.conversation_id,payload:{request_id:c.request_id,run_id:'accepted-run',conversation_id:c.conversation_id,user_message_id:'accepted-message',started_at:new Date().toISOString()}})})); }""")
    await expect(page.locator('textarea')).to_have_value('Newer draft')
    await expect(page.get_by_title('sent.txt', exact=True)).to_have_count(0)
    await expect(page.get_by_title('newer.txt', exact=True)).to_be_visible()


@pytest.mark.parametrize('archived', [False, True])
async def test_recovery_missing_conversation(cockpit_page, archived):
    page = cockpit_page
    if archived:
        await page.evaluate("""() => { window.__qaSockets.at(-1).send(JSON.stringify({protocol_version:1,type:'archive_conversation',request_id:'archive-offline',session_id:sessionStorage.getItem('agy_session_id'),payload:{conversation_id:sessionStorage.getItem('agy_active_conversation_id')}})); }""")
        await expect(page.locator('aside').first.get_by_role('button', name='Archive Conversation')).to_have_count(0)
    else:
        await page.evaluate("sessionStorage.setItem('agy_active_conversation_id', '00000000000000000000000000000000')")
    await page.reload()
    await expect(page.get_by_role('button', name='New Conversation', exact=True)).to_be_enabled()
    await expect(page.get_by_role('heading', name='No Conversation Selected', exact=True)).to_be_visible()


async def test_switch_and_reconnect_during_council_critique(cockpit_page):
    page = cockpit_page
    await rename(page, 'Council A')
    await page.get_by_role('button', name='Open AI Council Swarm Panel').click()
    await page.get_by_role('button', name='Deliberate', exact=True).click()
    await page.get_by_role('textbox', name='Council question or topic').fill('stage2-hold: discuss isolated drafts')
    await page.get_by_role('button', name='Start Council', exact=True).click()
    await expect(page.get_by_text('critique · architect · running')).to_be_visible(timeout=10000)
    await page.get_by_role('button', name='New Conversation', exact=True).click()
    await expect(page.locator('header h2')).to_have_text('New Conversation')
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0)
    await page.locator('aside').first.get_by_text('Council A', exact=True).click()
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_be_visible()
    await page.evaluate('window.__qaSockets.at(-1).close()')
    await page.wait_for_function('() => window.__qaSockets.at(-1)?.readyState === 1')
    await expect(page.get_by_text('critique · architect · running')).to_be_visible(timeout=10000)
    await expect(page.get_by_text('analysis · architect · completed')).to_have_count(1)
    await page.get_by_role('button', name='Stop', exact=True).click()
    await expect(page.get_by_role('button', name='Stop', exact=True)).to_have_count(0, timeout=5000)
