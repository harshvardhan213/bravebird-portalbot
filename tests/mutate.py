"""DOM mutations used to prove the resolver survives markup changes.

Each mutation runs inside a real browser on a loaded fixture:

  rename_classes   every class name replaced with a random token (ids too, with --ids)
  reorder          children of every container holding form controls are reversed
  wrap             each form control's parent is wrapped in two extra <div>s
  iframe           the whole <form> is moved into a same-origin <iframe srcdoc=...>

CLI (writes mutated copies for eyeballing):
  python tests/mutate.py tests/fixtures/github_login.html --out /tmp/mutated
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

MUTATIONS = ("rename_classes", "reorder", "wrap", "iframe")

_JS = {
    "rename_classes": """(withIds) => {
        const tok = () => 'x' + Math.random().toString(36).slice(2, 9);
        for (const el of document.querySelectorAll('[class]')) {
            el.className = Array.from(el.classList).map(tok).join(' ');
        }
        if (withIds) {
            for (const el of document.querySelectorAll('[id]')) {
                const old = el.id, neu = tok();
                el.id = neu;
                for (const l of document.querySelectorAll(`label[for="${CSS.escape(old)}"]`)) l.htmlFor = neu;
            }
        }
    }""",
    "reorder": """() => {
        const parents = new Set();
        for (const c of document.querySelectorAll('input, select, textarea, button, label')) {
            if (c.parentElement && c.parentElement !== document.body) parents.add(c.parentElement);
        }
        for (const p of parents) {
            const kids = Array.from(p.children);
            // keep each <label> immediately before the control it describes
            const groups = [];
            for (const k of kids) {
                if (k.tagName === 'LABEL' || !groups.length || groups[groups.length-1].done) groups.push({els: [k], done: k.tagName !== 'LABEL'});
                else { groups[groups.length-1].els.push(k); groups[groups.length-1].done = true; }
            }
            groups.reverse().forEach(g => g.els.forEach(e => p.appendChild(e)));
        }
    }""",
    "wrap": """() => {
        const parents = new Set();
        for (const c of document.querySelectorAll('input, select, textarea, button')) {
            if (c.parentElement && c.parentElement.tagName !== 'BODY') parents.add(c.parentElement);
        }
        for (const p of parents) {
            const outer = document.createElement('div'), inner = document.createElement('div');
            outer.className = 'wrap-outer'; inner.className = 'wrap-inner';
            p.parentNode.insertBefore(outer, p);
            outer.appendChild(inner); inner.appendChild(p);
        }
    }""",
    "iframe": """() => {
        const form = document.querySelector('form');
        if (!form) throw new Error('no <form> to move');
        const frame = document.createElement('iframe');
        frame.name = 'moved-form';
        frame.style.width = '800px'; frame.style.height = '700px'; frame.style.border = '0';
        const head = document.head.innerHTML.replace(/<script[\\s\\S]*?<\\/script>/gi, '');
        frame.srcdoc = `<!doctype html><html><head>${head}</head><body>${form.outerHTML}</body></html>`;
        form.replaceWith(frame);
    }""",
}


async def apply(page, *names: str, rename_ids: bool = False) -> None:
    """Apply mutations in order to the page that is already loaded."""
    for n in names:
        if n not in _JS:
            raise ValueError(f"unknown mutation {n}")
        if n == "rename_classes":
            await page.evaluate(_JS[n], rename_ids)
        else:
            await page.evaluate(_JS[n])
        if n == "iframe":
            await page.wait_for_function("() => { const f = document.querySelector('iframe[name=\"moved-form\"]');"
                                         " return f && f.contentDocument && f.contentDocument.querySelector('form'); }")


async def _cli(src: Path, out: Path) -> None:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        page = await b.new_page()
        for n in MUTATIONS:
            await page.set_content(src.read_text())
            await apply(page, n)
            (out / f"{src.stem}.{n}.html").write_text(await page.content())
            print("wrote", out / f"{src.stem}.{n}.html")
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture", type=Path)
    ap.add_argument("--out", type=Path, default=Path("mutated"))
    a = ap.parse_args()
    asyncio.run(_cli(a.fixture, a.out))
