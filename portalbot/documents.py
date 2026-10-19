"""Document capture, two mechanisms:

1. Native download: clicking the artifact starts a browser download (a zip);
   we catch Playwright's download event, save it, and unzip the PDF.
2. Print to PDF: the run summary page printed by Chromium. page.pdf() only
   works headless, so this uses a separate headless browser with the same
   saved session.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from playwright.async_api import Page, Playwright

from .errors import FinalError

log = logging.getLogger("portalbot.documents")


async def download_artifact(page: Page, run: dict, out_dir: Path) -> tuple:
    """Returns (zip path, pdf path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    await page.goto(run["url"], wait_until="domcontentloaded")
    # Each artifact row has two links (name + download icon) to the same URL; either works.
    link = page.locator(f'a[href*="/actions/runs/{run["id"]}/artifacts/"]').first
    await link.wait_for(timeout=20000)

    async with page.expect_download(timeout=60000) as info:
        await link.click()
    download = await info.value
    zip_path = out_dir / download.suggested_filename
    await download.save_as(zip_path)
    log.info("downloaded %s", zip_path.name)

    with zipfile.ZipFile(zip_path) as z:
        pdf_names = [n for n in z.namelist() if n.lower().endswith(".pdf")]
        if not pdf_names:
            raise FinalError(f"{zip_path.name} contains no PDF")
        pdf_path = out_dir / Path(pdf_names[0]).name
        pdf_path.write_bytes(z.read(pdf_names[0]))
    log.info("extracted %s", pdf_path.name)
    return zip_path, pdf_path


async def print_page(pw: Playwright, state_file: Path, url: str, out: Path) -> Path:
    browser = await pw.chromium.launch(headless=True)
    try:
        context = await browser.new_context(storage_state=str(state_file))
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)  # let the run summary render
        await page.pdf(path=str(out), format="A4", print_background=True)
    finally:
        await browser.close()
    log.info("printed %s", out.name)
    return out
