"""Environment settings and input-file loading."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from . import redact


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    totp_secret: str
    headless: bool
    state_dir: Path
    runs_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        missing = [k for k in ("GH_USERNAME", "GH_PASSWORD", "GH_TOTP_SECRET") if not os.getenv(k)]
        if missing:
            raise ConfigError(f"missing env vars: {', '.join(missing)} (see .env.example)")
        s = cls(
            username=os.environ["GH_USERNAME"].strip(),
            password=os.environ["GH_PASSWORD"],
            totp_secret=os.environ["GH_TOTP_SECRET"].replace(" ", "").upper(),
            headless=os.getenv("HEADLESS", "false").lower() in ("1", "true", "yes"),
            state_dir=Path(os.getenv("STATE_DIR", "state")),
            runs_dir=Path(os.getenv("RUNS_DIR", "runs")),
        )
        # Register before anything can log them.
        redact.register(s.username, s.password, s.totp_secret)
        return s

    @property
    def state_file(self) -> Path:
        return self.state_dir / "github.json"


@dataclass(frozen=True)
class JobInput:
    portal: str
    repo: str
    workflow: str
    branch: str
    fields: dict[str, str]
    capture: dict = field(default_factory=dict)
    fault: str | None = None  # "break" key: a resolver target to disable, to demo a failure
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "JobInput":
        p = Path(path)
        try:
            data = json.loads(p.read_text())
        except FileNotFoundError:
            raise ConfigError(f"input file not found: {p}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"input file is not valid JSON: {p}: {e}")

        missing = [k for k in ("repo", "workflow", "branch", "fields") if k not in data]
        if missing:
            raise ConfigError(f"input is missing {missing}")

        return cls(
            portal=data.get("portal", "github"),
            repo=data["repo"],
            workflow=data["workflow"],
            branch=data["branch"],
            fields={k: str(v) for k, v in data["fields"].items()},
            capture=data.get("capture", {}),
            fault=data.get("break"),
            raw=data,
        )
