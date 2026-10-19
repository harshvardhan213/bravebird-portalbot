"""Find the workflow run we just started and wait for it to finish.

Each run in the list on the workflow page has an accessible label like
  "completed successfully: Run 3 of Generate report. invoice 2026-09 acme"
so status and title come straight from it.
"""
from __future__ import annotations

import logging
import re
import time

from playwright.async_api import Page

from .errors import FinalError, RetryableError

log = logging.getLogger("portalbot.runs")


async def list_runs(page: Page) -> list:
    """Newest first: [{id, url, status, title}]."""
    rows = await page.evaluate("""() => [...document.querySelectorAll('li[aria-label]')]
        .map(li => ({label: li.getAttribute('aria-label'),
                     href: li.querySelector('a[href*="/actions/runs/"]')?.href}))
        .filter(r => r.href)""")
    runs = []
    for r in rows:
        status, _, rest = r["label"].partition(":")
        runs.append({
            "id": int(re.search(r"/actions/runs/(\d+)", r["href"]).group(1)),
            "url": r["href"].split("?")[0],
            "status": status.strip(),
            "title": rest.split(". ", 1)[-1].strip(),
        })
    return runs


async def wait_for_run(page: Page, workflow_url: str, known_ids: set, timeout_s: int = 300, poll_s: float = 5) -> dict:
    """Reload the workflow page until a run we hadn't seen before finishes."""
    deadline = time.monotonic() + timeout_s
    last_status = None
    while time.monotonic() < deadline:
        await page.goto(workflow_url, wait_until="domcontentloaded")
        new = [r for r in await list_runs(page) if r["id"] not in known_ids]
        if new:
            run = new[0]
            if run["status"] != last_status:
                log.info("run %s: %s", run["id"], run["status"])
                last_status = run["status"]
            if run["status"] == "completed successfully":
                return run
            if "fail" in run["status"] or "cancel" in run["status"]:
                raise FinalError(f"workflow run ended as '{run['status']}': {run['url']}")
        await page.wait_for_timeout(poll_s * 1000)
    raise RetryableError(f"run did not finish within {timeout_s}s")
