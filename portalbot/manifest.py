"""Run manifest: inputs, pages visited, stage timings, captured files.

One manifest per run, written to runs/<run_id>/manifest.json. It is rewritten
after every stage so a crash still leaves a partial record.
"""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .redact import redact_obj


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def make_run_id(inputs: dict) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:6]
    return f"{stamp}-{digest}"


class Manifest:
    def __init__(self, run_dir: Path, run_id: str, input_path: str, inputs: dict):
        self.run_dir = run_dir
        self.path = run_dir / "manifest.json"
        self._t0 = time.perf_counter()
        self.data = {
            "run_id": run_id,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "duration_ms": None,
            "input_file": input_path,
            "inputs": inputs,
            "session": None,  # "reused" | "relogin" | "fresh"
            "pages_visited": [],
            "stages": [],
            "files": [],
            "error": None,
        }
        run_dir.mkdir(parents=True, exist_ok=True)
        self.save()

    # --- recording -------------------------------------------------------
    def page_visited(self, url: str, title: str | None = None) -> None:
        pages = self.data["pages_visited"]
        if pages and pages[-1]["url"] == url:
            return
        pages.append({"url": url, "title": title, "at": _now()})

    def set_session(self, mode: str) -> None:
        self.data["session"] = mode

    def add_file(self, path: Path, kind: str, source: str) -> dict:
        blob = path.read_bytes()
        entry = {
            "path": str(path.relative_to(self.run_dir) if path.is_relative_to(self.run_dir) else path),
            "kind": kind,  # "pdf" | "zip" | ...
            "source": source,  # "download" | "print_to_pdf" | "blob"
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        self.data["files"].append(entry)
        self.save()
        return entry

    @contextmanager
    def stage(self, key: str):
        entry = {"key": key, "status": "running", "started_at": _now(), "duration_ms": None, "attempts": 0}
        self.data["stages"].append(entry)
        t = time.perf_counter()
        try:
            yield entry
            entry["status"] = "ok"
        except BaseException as e:
            entry["status"] = "failed"
            entry["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            entry["duration_ms"] = round((time.perf_counter() - t) * 1000)
            self.save()

    def finish(self, status: str, error: str | None = None) -> None:
        self.data["status"] = status
        self.data["error"] = error
        self.data["finished_at"] = _now()
        self.data["duration_ms"] = round((time.perf_counter() - self._t0) * 1000)
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(redact_obj(self.data), indent=2))
