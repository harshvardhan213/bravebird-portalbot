"""Evidence bundle written when a run fails for good.

runs/<id>/evidence/
  screenshot.png   input fields and the account name masked
  page.html        redacted
  url.txt          redacted
  console.log      redacted
  error.json       stage key, error, resolver attempts (redacted)

Everything text-based goes through redact.redact(), which removes the
password, TOTP secret, generated codes, username/email, cookies and tokens.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from playwright.async_api import Page

from . import resolver
from .redact import redact, redact_obj

log = logging.getLogger("portalbot.evidence")


async def write_bundle(page: Page | None, console: list, out_dir: Path, stage: str, error: Exception,
                       username: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if page is not None and not page.is_closed():
        try:
            # Blank every typed value so a password or code can't appear in the screenshot.
            await page.evaluate("() => document.querySelectorAll('input, textarea').forEach(e => { e.value = ''; })")
            # Mask inputs and anything showing the account name (breadcrumbs, "run by ...", avatar).
            mask = [page.locator("input, textarea"),
                    page.get_by_text(re.compile(re.escape(username), re.I)),
                    page.locator('img[alt*="avatar" i], img.avatar')]
            await page.screenshot(path=str(out_dir / "screenshot.png"), mask=mask)
            (out_dir / "page.html").write_text(redact(await page.content()))
            (out_dir / "url.txt").write_text(redact(page.url) + "\n")
        except Exception as e:  # the page may be mid-navigation or crashed
            log.warning("could not capture page: %s", e)

    (out_dir / "console.log").write_text(redact("\n".join(console)) + "\n")
    attempts = [h for h in resolver.HISTORY if h["winner"] is None][-5:] or resolver.HISTORY[-5:]
    (out_dir / "error.json").write_text(json.dumps(redact_obj({
        "stage": stage,
        "error": f"{type(error).__name__}: {error}",
        "resolver_attempts": attempts,
    }), indent=2))
    log.error("evidence bundle written to %s", out_dir)
    return out_dir
