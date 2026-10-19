"""GitHub login: username + password, then the TOTP code.

  /login -> submit username + password
         -> /sessions/two-factor/app -> type the code (GitHub submits at 6 digits)
            still on the 2FA page = code rejected -> one retry with the next code
            rejected again -> CodeRejected (final)
         -> signed in: <meta name="user-login"> is our username
"""
from __future__ import annotations

import logging
import re

from playwright.async_api import Page, TimeoutError as PWTimeout

from .codes import Challenge, CodeProvider
from .errors import CodeRejected, LoginFailed
from .resolver import Target, present, resolve

log = logging.getLogger("portalbot.login")

BASE = "https://github.com"

USERNAME = Target(
    "login.username",
    role="textbox", name="Username or email address",
    label="Username or email address",
    structure=['input[autocomplete="username"]', 'input[name="login"]'],
    css=["#login_field"],
)
PASSWORD = Target(
    "login.password",
    label="Password",
    text="Password",
    structure=['input[autocomplete="current-password"]', 'input[name="password"]'],
    css=["#password"],
)
SIGN_IN = Target(
    "login.submit",
    role="button", name="Sign in",
    structure=['input[type="submit"][name="commit"]'],
)
OTP_FIELD = Target(
    "login.otp",
    label=re.compile(r"authentication code", re.I),
    structure=['input[autocomplete="one-time-code"]', 'input[name="app_otp"]'],
    css=["#app_totp"],
)


async def logged_in_as(page: Page) -> str | None:
    """The username GitHub says this page belongs to, or None when signed out."""
    meta = page.locator('meta[name="user-login"]')
    if await meta.count() == 0:
        return None
    return await meta.first.get_attribute("content") or None


async def login(page: Page, username: str, password: str, codes: CodeProvider) -> None:
    await page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    await (await resolve(page, USERNAME)).fill(username)
    await (await resolve(page, PASSWORD)).fill(password)
    await (await resolve(page, SIGN_IN)).click()

    try:
        await page.wait_for_url(lambda url: "/login" not in url and not url.endswith("/session"), timeout=15000)
    except PWTimeout:
        raise LoginFailed("still on the login page: username or password rejected")

    if "/sessions/two-factor" in page.url:
        if not await present(page, OTP_FIELD):
            # GitHub may open on another 2FA method (passkey, mobile app); switch to the authenticator app.
            await page.goto(f"{BASE}/sessions/two-factor/app", wait_until="domcontentloaded")
        await _enter_code(page, codes)

    if (await logged_in_as(page) or "").lower() != username.lower():
        raise LoginFailed(f"login ended on {page.url} without being signed in")
    log.info("signed in")


async def _enter_code(page: Page, codes: CodeProvider) -> None:
    for attempt in (1, 2):
        code = await codes.get_code(Challenge(kind="totp", attempt=attempt))
        field = await resolve(page, OTP_FIELD)
        await field.fill("")
        await field.type(code, delay=40)  # typing the 6th digit makes GitHub submit
        try:
            await page.wait_for_url(lambda url: "/sessions/two-factor" not in url, timeout=8000)
            return
        except PWTimeout:
            log.warning("2fa: code rejected (attempt %d)", attempt)
    raise CodeRejected("authentication code rejected twice")
