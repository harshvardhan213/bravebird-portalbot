"""Second-factor code providers.

The runner only depends on `CodeProvider.get_code(challenge) -> str`, so an
IMAP or SMS-inbox provider can be dropped in without touching the login flow.
Codes are registered with the redactor the moment they exist and are never
logged.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import pyotp

from . import redact

log = logging.getLogger("portalbot.codes")


@dataclass
class Challenge:
    kind: str  # "totp" | "email" | "sms"
    attempt: int = 1  # 1 = first try, 2 = retry after a rejected code
    portal: str = "github"


class CodeProvider(Protocol):
    async def get_code(self, challenge: Challenge) -> str: ...


class TotpProvider:
    """Generates RFC 6238 codes from the shared secret.

    - Avoids handing out a code that expires within `min_validity` seconds,
      so it can't go stale between typing and the server checking it.
    - Never returns the same time-step twice: a retry always waits for the
      next window (servers reject reused codes, and if the first was rejected
      for clock skew the next window is the useful one).
    """

    def __init__(self, secret: str, min_validity: int = 5, clock=time.time):
        self._totp = pyotp.TOTP(secret)
        self._min_validity = min_validity
        self._clock = clock
        self._last_step: int | None = None

    def _step(self, t: float) -> int:
        return int(t // self._totp.interval)

    def _seconds_left(self, t: float) -> float:
        return self._totp.interval - (t % self._totp.interval)

    async def get_code(self, challenge: Challenge) -> str:
        if challenge.kind != "totp":
            raise ValueError(f"TotpProvider cannot answer a {challenge.kind} challenge")

        while True:
            now = self._clock()
            step = self._step(now)
            left = self._seconds_left(now)
            if step == self._last_step:
                reason = "waiting for next window (previous code used)"
            elif left < self._min_validity:
                reason = f"current window ends in {left:.1f}s"
            else:
                break
            log.info("totp: %s, sleeping %.1fs", reason, left + 0.2)
            await asyncio.sleep(left + 0.2)

        self._last_step = step
        code = self._totp.at(now)
        redact.register(code)
        log.info("totp: code generated for attempt %d (valid ~%ds)", challenge.attempt, int(left))
        return code
