"""Compatibility smoke test using isolated, readiness-checked browser fixtures."""
import pytest
pytest.importorskip('playwright')
from playwright.async_api import expect
from tests.e2e.cockpit_browser_support import cockpit_url
from tests.e2e.test_exploratory_regressions import cockpit_page


async def test_cockpit_ui_loads_and_runs_without_black_screen(cockpit_page):
    page = cockpit_page
    assert len(await page.locator('#root').inner_html()) > 500
    await expect(page.get_by_role('textbox', name='Ask Antigravity anything... (Type @ to mention files, / for commands)')).to_be_enabled()
    await page.locator('header button[title="Changed Files & Diffs"]').click()
    await expect(page.get_by_role('button', name='Close panel', exact=True)).to_be_visible()
    await page.get_by_role('button', name='Close panel', exact=True).click()
    await page.get_by_role('button', name='Settings', exact=True).click()
    await expect(page.get_by_role('dialog', name='Cockpit Settings')).to_be_visible()
    await page.get_by_role('button', name='Cancel', exact=True).click()
    context = await page.context.browser.new_context()
    direct = await context.new_page()
    errors = []
    direct.on('pageerror', lambda error: errors.append(str(error)))
    await direct.goto(page.url.split('?')[0])
    await expect(direct.get_by_role('heading', name='No Conversation Selected')).to_be_visible()
    assert await direct.evaluate('async () => (await fetch("/api/models")).status') == 401
    assert not errors
    await context.close()
