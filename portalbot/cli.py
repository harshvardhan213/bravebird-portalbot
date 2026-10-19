"""Command-line entry point.

  python -m portalbot run --input inputs/main-invoice.json
  python -m portalbot doctor
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from playwright.async_api import async_playwright

from . import documents, form, redact, resolver, runs
from .browser import Session
from .codes import TotpProvider
from .config import ConfigError, JobInput, Settings
from .evidence import write_bundle
from .login import login
from .manifest import Manifest, make_run_id
from .navigate import open_run_dialog, to_workflow
from .retry import with_retry
from .session import restore

log = logging.getLogger("portalbot")


async def run(input_path: str) -> int:
    settings = Settings.from_env()
    job = JobInput.load(input_path)
    run_id = make_run_id(job.raw)
    run_dir = settings.runs_dir / run_id
    manifest = Manifest(run_dir, run_id, input_path, job.raw)
    codes = TotpProvider(settings.totp_secret)
    log.info("run %s", run_id)

    if job.fault:
        resolver.disable(job.fault)  # input "break": that element can never be found
        log.info("break: target %s disabled to demonstrate a failure", job.fault)

    async with async_playwright() as pw:
        session = Session(pw, manifest, headless=settings.headless)
        page = None
        stage = "start"

        async def step(name: str, fn, retry: bool = True):
            nonlocal stage
            stage = name
            with manifest.stage(name):
                return await (with_retry(name, fn) if retry else fn())

        try:
            settings.state_dir.mkdir(parents=True, exist_ok=True)
            had_state = settings.state_file.exists()
            page, reason = await step("session", lambda: restore(session, settings.state_file, settings.username))

            if reason is None:
                manifest.set_session("reused")
            else:
                async def do_login():
                    await login(page, settings.username, settings.password, codes)
                    await session.save_state(settings.state_file)
                await step("login", do_login)
                manifest.set_session("relogin" if had_state else "fresh")

            workflow_url = await step("navigate", lambda: to_workflow(page, job.repo, job.workflow))
            known_ids = {r["id"] for r in await runs.list_runs(page)}

            async def do_fill():
                await page.goto(workflow_url, wait_until="domcontentloaded")  # clean start on a retry
                await open_run_dialog(page)
                fields = await form.choose_branch(page, job.branch)
                form.check_inputs(fields, job.fields, job.branch)
                await form.fill(page, fields, job.fields)
            await step("fill_form", do_fill)

            # Not retried: a second click could start the workflow twice.
            await step("submit", lambda: form.submit(page), retry=False)

            gh_run = await step("wait_run", lambda: runs.wait_for_run(page, workflow_url, known_ids))
            manifest.data["workflow_run"] = gh_run

            async def do_capture():
                files = run_dir / "files"
                zip_path, pdf_path = await documents.download_artifact(page, gh_run, files)
                manifest.add_file(zip_path, "zip", "download")
                manifest.add_file(pdf_path, "pdf", "download (unzipped)")
                if job.capture.get("print_run_page"):
                    out = await documents.print_page(pw, settings.state_file, gh_run["url"], files / "run-summary.pdf")
                    manifest.add_file(out, "pdf", "print_to_pdf")
            await step("capture", do_capture)

            manifest.finish("ok")
            log.info("done in %.1fs, manifest: %s", manifest.data["duration_ms"] / 1000, manifest.path)
            return 0
        except Exception as e:
            log.error("run failed at stage '%s': %s: %s", stage, type(e).__name__, e)
            await write_bundle(page, list(session.console), run_dir / "evidence", stage, e, settings.username)
            manifest.finish("failed", f"{stage}: {type(e).__name__}: {e}")
            return 1
        finally:
            await session.close()


def doctor() -> int:
    settings = Settings.from_env()
    redact.register(TotpProvider(settings.totp_secret)._totp.now())  # fails if the secret isn't valid base32
    print("GH_USERNAME, GH_PASSWORD, GH_TOTP_SECRET: set")
    print("TOTP secret: valid")
    return 0


def main(argv=None) -> int:
    redact.setup_logging()
    p = argparse.ArgumentParser(prog="portalbot")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a job from an input JSON file")
    r.add_argument("--input", required=True)
    sub.add_parser("doctor", help="check .env and the TOTP secret")
    args = p.parse_args(argv)
    try:
        return asyncio.run(run(args.input)) if args.cmd == "run" else doctor()
    except ConfigError as e:
        log.error("config: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
