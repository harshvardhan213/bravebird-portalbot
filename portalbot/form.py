"""Fill and submit GitHub's "Run workflow" dialog.

The dependent field: the inputs shown come from the workflow file on the
*selected branch*. Picking a branch makes GitHub load that branch's file and
re-render the fields (v2 adds `region` and has different report types). So we
pick the branch first, wait for the re-render, then read which fields exist
before filling anything.
"""
from __future__ import annotations

import logging
import re

from playwright.async_api import Page

from .errors import FinalError
from .resolver import ResolveError, Target, resolve

log = logging.getLogger("portalbot.form")

DIALOG = '[role="dialog"]'

BRANCH_BUTTON = Target(
    "form.branch_button", scope=DIALOG,
    role="button", name=re.compile(r"^Use workflow from"),
    structure=['button[aria-label^="Use workflow from"]'],
)
SUBMIT = Target(
    "form.submit", scope=DIALOG,
    role="button", name="Run workflow",
    structure=['button[type="submit"][form]'],
)


class FormMismatch(FinalError):
    """The input file asks for a field or value this branch's form doesn't have."""


def field_target(key: str, label: str | None) -> Target:
    return Target(
        f"form.field.{key}",
        label=re.compile(rf"^\s*{re.escape(label)}") if label else None,
        text=label,
        structure=[f'[name="inputs[{key}]"]'],
    )


async def read_fields(page: Page) -> dict:
    """Fields the dialog shows right now: key -> {kind, options, label}."""
    return await page.locator(DIALOG).first.evaluate("""(d) => {
        const out = {};
        for (const el of d.querySelectorAll('[name^="inputs["]')) {
            const label = el.id ? d.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
            out[el.name.slice(7, -1)] = {
                kind: el.tagName === 'SELECT' ? 'choice' : 'text',
                options: el.tagName === 'SELECT' ? [...el.options].map(o => o.value) : null,
                label: label ? label.innerText.replace(/\\*\\s*$/, '').trim() : null,
            };
        }
        return out;
    }""")


async def _selected_branch(page: Page) -> str | None:
    return await page.locator(f'{DIALOG} input[name="branch"]').first.get_attribute("value")


async def choose_branch(page: Page, branch: str) -> dict:
    await page.locator(DIALOG).first.wait_for()
    if await _selected_branch(page) == branch:
        log.info("branch already %s", branch)
        return await read_fields(page)

    before = await read_fields(page)
    await (await resolve(page, BRANCH_BUTTON)).click()

    # The branch list opens as a menu outside the dialog.
    item = None
    for role in ("option", "menuitemradio"):
        try:
            item = await resolve(page, Target(f"form.branch.{role}", role=role, name=branch), timeout_ms=2000, quiet=True)
            break
        except ResolveError:
            continue
    if item is None:
        raise FormMismatch(f"branch {branch!r} not found in the branch menu")
    await item.click()

    # Wait for GitHub to load that branch's workflow file and re-render the inputs.
    await page.wait_for_function(
        """(b) => {
            const d = document.querySelector('[role="dialog"]');
            return d && d.querySelector('input[name="branch"]')?.value === b
                     && !d.querySelector('[aria-busy="true"]');
        }""", arg=branch, timeout=15000)
    await page.wait_for_timeout(500)

    fields = await read_fields(page)
    log.info("branch -> %s: fields %s (were %s)", branch, sorted(fields), sorted(before))
    return fields


def check_inputs(fields: dict, wanted: dict, branch: str) -> None:
    unknown = sorted(set(wanted) - set(fields))
    if unknown:
        raise FormMismatch(f"branch {branch!r} has no field(s) {unknown}; it has {sorted(fields)}")
    for key, value in wanted.items():
        options = fields[key]["options"]
        if options and value not in options:
            raise FormMismatch(f"{key}={value!r} is not an option on branch {branch!r}; options: {options}")


async def fill(page: Page, fields: dict, wanted: dict) -> None:
    for key, value in wanted.items():
        el = await resolve(page, field_target(key, fields[key]["label"]))
        if fields[key]["kind"] == "choice":
            await el.select_option(value)
        else:
            await el.fill(value)
        log.info("filled %s", key)


async def submit(page: Page) -> None:
    await (await resolve(page, SUBMIT)).click()
    await page.locator(DIALOG).first.wait_for(state="hidden", timeout=15000)
    log.info("workflow dispatched")
