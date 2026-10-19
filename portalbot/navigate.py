"""Repo home -> Actions tab -> workflow page (three pages deep, real clicks)."""
from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from .errors import UnexpectedPage
from .login import BASE
from .resolver import Target, resolve

log = logging.getLogger("portalbot.navigate")

ACTIONS_TAB = Target(
    "nav.actions_tab",
    role="link", name=re.compile(r"^Actions\b"),
    structure=['a[data-tab-item="actions"]'],
    css=["#actions-tab"],
)
RUN_WORKFLOW_BUTTON = Target("nav.run_workflow", role="button", name="Run workflow")


def workflow_link(name: str) -> Target:
    return Target("nav.workflow_link", role="link", name=name,
                  structure=[f'a[href*="/actions/workflows/"]:text-is("{name}")'])


async def to_workflow(page: Page, repo: str, workflow: str) -> str:
    """Returns the workflow page URL."""
    resp = await page.goto(f"{BASE}/{repo}", wait_until="domcontentloaded")
    if resp and resp.status == 404:
        raise UnexpectedPage(f"repo {repo} not found")
    log.info("page 1: repo home")

    await (await resolve(page, ACTIONS_TAB)).click()
    await page.wait_for_url(re.compile(r"/actions/?$"))
    log.info("page 2: actions")

    await (await resolve(page, workflow_link(workflow))).click()
    await page.wait_for_url(re.compile(r"/actions/workflows/"))
    log.info("page 3: workflow '%s'", workflow)
    return page.url.split("?")[0]


async def open_run_dialog(page: Page) -> None:
    await (await resolve(page, RUN_WORKFLOW_BUTTON)).click()
    log.info("run workflow dialog opened")
