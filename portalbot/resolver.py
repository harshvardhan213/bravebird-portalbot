"""Multi-strategy element resolver.

A target is described by *what it is*, not by one CSS string. Strategies are
tried from most to least stable, in the main page and in every iframe:

  1. role       accessible role + name  (survives restyling and markup changes)
  2. label      <label> text             (what the user reads)
  3. text       the control right after some visible text
  4. structure  stable form structure    (input[name=...], autocomplete=: tied to what the form posts)
  5. css        ids / classes            (last: build tools regenerate these)

A strategy wins only if it finds exactly one visible element. If it finds
several, that's "ambiguous" and we move on instead of guessing. Every attempt
is recorded so a failure explains itself.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Pattern, Union

from playwright.async_api import Frame, Locator, Page

from .errors import FinalError

log = logging.getLogger("portalbot.resolver")

Text = Union[str, Pattern]


@dataclass(eq=False)
class Target:
    key: str  # used in logs and for fault injection, e.g. "login.password"
    role: Optional[str] = None
    name: Optional[Text] = None
    label: Optional[Text] = None
    text: Optional[str] = None
    structure: list = field(default_factory=list)
    css: list = field(default_factory=list)
    scope: Optional[str] = None  # search inside this container, e.g. '[role="dialog"]'


class ResolveError(FinalError):
    def __init__(self, target: Target, attempts: list):
        self.target = target
        self.attempts = attempts
        tried = ", ".join(f"{a['strategy']}:{a['outcome']}" for a in attempts)
        super().__init__(f"could not resolve {target.key} ({tried})")


HISTORY: list = []  # recent resolutions, included in failure evidence
_disabled: set = set()  # fault injection: every strategy runs but can't match


def disable(key: str) -> None:
    _disabled.add(key)


def _strategies(t: Target, frame: Frame):
    for strategy, detail, loc in _all_strategies(t, frame):
        if t.key in _disabled:
            loc = loc.locator("xpath=self::*[@data-never-matches]")
        yield strategy, detail, loc


def _all_strategies(t: Target, frame: Frame):
    root = frame.locator(t.scope) if t.scope else frame
    if t.role:
        exact = isinstance(t.name, str)
        yield "role", f"{t.role}[{_show(t.name)}]", root.get_by_role(t.role, name=t.name, exact=exact)
    if t.label is not None:
        yield "label", _show(t.label), root.get_by_label(t.label, exact=isinstance(t.label, str))
    if t.text:
        xpath = (f"xpath=.//*[normalize-space(text())='{t.text}']"
                 "/following::*[self::input or self::select or self::textarea][1]")
        yield "text", t.text, root.locator(xpath)
    for sel in t.structure:
        yield "structure", sel, root.locator(sel)
    for sel in t.css:
        yield "css", sel, root.locator(sel)


def _show(v) -> str:
    return v.pattern if isinstance(v, re.Pattern) else str(v)


async def _visible(loc: Locator) -> list:
    return [loc.nth(i) for i in range(min(await loc.count(), 10)) if await loc.nth(i).is_visible()]


async def resolve(page: Page, t: Target, timeout_ms: int = 8000, quiet: bool = False) -> Locator:
    """Return exactly one visible element for the target, or raise ResolveError."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        attempts = []
        for frame in page.frames:
            where = "main" if frame == page.main_frame else "iframe"
            for strategy, detail, loc in _strategies(t, frame):
                try:
                    found = await _visible(loc)
                except Exception:
                    found = []
                outcome = {0: "none", 1: "won"}.get(len(found), "ambiguous")
                attempts.append({"strategy": strategy, "detail": detail, "frame": where, "outcome": outcome})
                if outcome == "won":
                    HISTORY.append({"target": t.key, "winner": f"{strategy} ({detail}) in {where}",
                                    "attempts": attempts})
                    if not quiet:
                        log.info("resolve %-22s -> %s (%s)%s", t.key, strategy, detail,
                                 "" if where == "main" else " in iframe")
                    return found[0]
        if time.monotonic() >= deadline:
            if not quiet:
                HISTORY.append({"target": t.key, "winner": None, "attempts": attempts})
                log.error("resolve %s failed after %d attempts", t.key, len(attempts))
            raise ResolveError(t, attempts)
        await page.wait_for_timeout(250)


async def present(page: Page, t: Target) -> bool:
    try:
        await resolve(page, t, timeout_ms=0, quiet=True)
        return True
    except ResolveError:
        return False
