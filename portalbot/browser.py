"""Browser/session plumbing shared by all stages.

`Session` owns the Playwright browser, context and page, records every
main-frame navigation into the manifest, and keeps a rolling console log for
evidence bundles.
"""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright

from .manifest import Manifest

log = logging.getLogger("portalbot.browser")

# GitHub sometimes serves a reduced page to the bare headless UA string.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


class Session:
    def __init__(self, pw: Playwright, manifest: Manifest, headless: bool):
        self.pw = pw
        self.manifest = manifest
        self.headless = headless
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.console: deque[str] = deque(maxlen=500)

    async def open(self, storage_state: Path | None = None) -> Page:
        """Open a fresh context (closing any previous one), optionally loading saved state."""
        if self.browser is None:
            self.browser = await self.pw.chromium.launch(headless=self.headless)
        if self.context is not None:
            await self.context.close()
        self.context = await self.browser.new_context(
            storage_state=str(storage_state) if storage_state else None,
            accept_downloads=True,
            user_agent=_UA,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        self.page = await self.context.new_page()
        self._watch(self.page)
        self.context.on("page", self._watch)  # new tabs / popups
        return self.page

    def _watch(self, page: Page) -> None:
        def on_nav(frame):
            if frame == page.main_frame:
                self.manifest.page_visited(frame.url)

        page.on("framenavigated", on_nav)
        page.on("console", lambda m: self.console.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: self.console.append(f"[pageerror] {e}"))

    async def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(path))
        try:
            path.chmod(0o600)  # cookies are credentials
        except OSError:
            pass
        log.info("session state saved")

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
