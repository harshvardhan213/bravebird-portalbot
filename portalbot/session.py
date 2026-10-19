"""Session reuse: load saved cookies, check they still work, otherwise log in again.

A saved session is reused only if all three checks pass:
  1. the state file is valid JSON with cookies           (catches a corrupted file)
  2. it contains GitHub's `user_session` cookie            (catches a logged-out save)
  3. an auth-only page opens and shows us as signed in     (catches a session GitHub killed)

Any failure deletes the file; the caller does a full login.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from playwright.async_api import Page

from .browser import Session
from .login import BASE, logged_in_as

log = logging.getLogger("portalbot.session")

PROBE_URL = f"{BASE}/settings/profile"  # redirects to /login when signed out


def check_file(path: Path) -> str | None:
    """Offline checks. Returns a reason the file is unusable, or None if it looks fine."""
    if not path.exists():
        return "no saved session"
    try:
        cookies = json.loads(path.read_text())["cookies"]
    except Exception:
        return "session file is corrupt"
    if not any(c.get("name") == "user_session" for c in cookies):
        return "no session cookie in file"
    return None


async def check_live(page: Page, username: str) -> str | None:
    await page.goto(PROBE_URL, wait_until="domcontentloaded", timeout=20000)
    if "/settings/profile" not in page.url:
        return "GitHub redirected away from an auth-only page"
    if (await logged_in_as(page) or "").lower() != username.lower():
        return "page is not signed in as the configured user"
    return None


async def restore(session: Session, state_file: Path, username: str) -> tuple[Page, str | None]:
    """Returns (page, reason). reason is None when the saved session was reused."""
    reason = check_file(state_file)
    if reason is None:
        page = await session.open(storage_state=state_file)
        reason = await check_live(page, username)
        if reason is None:
            log.info("session reused")
            return page, None

    log.warning("session not reusable: %s", reason)
    state_file.unlink(missing_ok=True)
    return await session.open(), reason  # clean context, no stale cookies

