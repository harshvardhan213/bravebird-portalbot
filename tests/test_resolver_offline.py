"""Resolver vs. mutated markup, fully offline.

Fixtures: GitHub's real login page and Run workflow dialog, saved as HTML.
Before mutating, each true element is tagged with data-truth (which no
strategy uses), so every assertion checks we found the *right* element, not
just *an* element.
"""
import re

import pytest
from playwright.async_api import async_playwright

from mutate import MUTATIONS, apply
from portalbot.form import BRANCH_BUTTON, SUBMIT, field_target
from portalbot.login import PASSWORD, SIGN_IN, USERNAME
from portalbot.resolver import HISTORY, ResolveError, Target, resolve

LOGIN_HTML = open("tests/fixtures/github_login.html").read()  # captured from github.com/login
FORM_HTML = open("tests/fixtures/real_dialog.html").read()  # captured from github.com
REPORT_TYPE = field_target("report_type", "Report type")
MONTH = field_target("month", "Billing month (YYYY-MM)")
CUSTOMER = field_target("customer", "Customer name")

CASES = {
    "login": (LOGIN_HTML, {
        USERNAME: "#login_field", PASSWORD: "#password", SIGN_IN: 'input[name="commit"]',
    }),
    "form": (FORM_HTML, {
        BRANCH_BUTTON: '[role=dialog] button[aria-haspopup="true"]',
        REPORT_TYPE: '[name="inputs[report_type]"]', MONTH: '[name="inputs[month]"]',
        CUSTOMER: '[name="inputs[customer]"]', SUBMIT: '[role=dialog] button[type="submit"]',
    }),
}

SCENARIOS = [(m,) for m in MUTATIONS] + [MUTATIONS] + [("rename_classes+ids",)]


@pytest.fixture(scope="module")
async def browser():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        yield b
        await b.close()


async def _load(browser, html, truth):
    page = await browser.new_page()
    # Block network: the captured login page references GitHub assets.
    await page.route("**/*", lambda r: r.abort() if not r.request.url.startswith("data:") else r.continue_())
    await page.set_content(html, wait_until="domcontentloaded")
    for t, sel in truth.items():
        n = await page.locator(sel).count()
        assert n >= 1, f"fixture lost {sel}"
        await page.locator(sel).first.evaluate("(e, k) => e.setAttribute('data-truth', k)", t.key)
    return page


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: "+".join(s))
async def test_resolves_through_mutations(browser, case, scenario):
    html, truth = CASES[case]
    page = await _load(browser, html, truth)
    try:
        if scenario == ("rename_classes+ids",):
            await apply(page, "rename_classes", rename_ids=True)
        else:
            await apply(page, *scenario)
        for target in truth:
            el = await resolve(page, target, timeout_ms=2000)
            assert await el.get_attribute("data-truth") == target.key, f"{target.key} resolved to the wrong element"
            winner = HISTORY[-1]["winner"]
            # The fragile tier must never be what saves us.
            assert not winner.startswith("css"), f"{target.key} only found via css: {winner}"
            if "iframe" in scenario and target.key.startswith(("login.", "form.field.")):
                assert "iframe" in winner  # these live inside the <form> that was moved
    finally:
        await page.close()


async def test_failure_explains_every_attempt(browser):
    page = await browser.new_page()
    await page.set_content("<form><input name='other'></form>")
    with pytest.raises(ResolveError) as ei:
        await resolve(page, MONTH, timeout_ms=300)
    tried = {a["strategy"] for a in ei.value.attempts}
    assert tried == {"label", "text", "structure"}
    assert all(a["outcome"] == "none" for a in ei.value.attempts)
    await page.close()


async def test_ambiguous_is_skipped_not_guessed(browser):
    page = await browser.new_page()
    await page.set_content("""<form>
      <input class="f" name="a"><input class="f" name="b">
      <label for="c">Customer name</label><input id="c" class="f" data-truth="yes">
    </form>""")
    t = Target("t", label="Customer name", css=[".f"])
    el = await resolve(page, t, timeout_ms=300)
    assert await el.get_attribute("data-truth") == "yes"
    t2 = Target("t2", css=[".f"])
    with pytest.raises(ResolveError) as ei:
        await resolve(page, t2, timeout_ms=300)
    assert ei.value.attempts[0]["outcome"] == "ambiguous"
    await page.close()


async def test_falls_back_when_labels_disappear(browser):
    """Labels removed (a common redesign): label and text fail, the name= structure takes over."""
    html, truth = CASES["form"]
    page = await _load(browser, html, truth)
    await page.evaluate("() => document.querySelectorAll('label').forEach(l => l.remove())")
    await apply(page, "rename_classes", "wrap")
    for target in (REPORT_TYPE, MONTH, CUSTOMER):
        el = await resolve(page, target, timeout_ms=1000)
        assert await el.get_attribute("data-truth") == target.key
        # label gone -> the form's name= structure takes over
        assert HISTORY[-1]["winner"].startswith("structure")
        assert HISTORY[-1]["attempts"][0]["strategy"] == "label"
        assert HISTORY[-1]["attempts"][0]["outcome"] == "none"
    await page.close()
