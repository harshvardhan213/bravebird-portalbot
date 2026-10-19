"""Central redaction: every log line and evidence file passes through here.

Secrets are registered at runtime (password, TOTP secret, each generated code,
username/email) and scrubbed wherever they appear. Pattern rules catch
secret-shaped values we never registered (CSRF tokens, session cookies).
"""
from __future__ import annotations

import logging
import re
import threading

MASK = "[REDACTED]"

_lock = threading.Lock()
_secrets: set[str] = set()

_PATTERNS = [
    # form tokens / hidden inputs GitHub embeds in HTML
    (re.compile(r'(name="(?:authenticity_token|timestamp_secret|otp|app_otp|password)"[^>]*value=")[^"]*(")', re.I), r"\1" + MASK + r"\2"),
    (re.compile(r'(value=")[^"]*("[^>]*name="(?:authenticity_token|timestamp_secret|otp|app_otp|password)")', re.I), r"\1" + MASK + r"\2"),
    # cookies / bearer tokens in URLs, headers, console output
    (re.compile(r"((?:user_session|_gh_sess|__Host-user_session_same_site|logged_in|dotcom_user)=)[^;\s&\"']+", re.I), r"\1" + MASK),
    (re.compile(r"(\b(?:token|access_token|code|otp|password|secret)=)[^&\s\"']+", re.I), r"\1" + MASK),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"), MASK),
    # email addresses
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
]


def register(*values: str | None) -> None:
    """Mark values as secret. Very short values are ignored to avoid shredding text."""
    with _lock:
        for v in values:
            if v and len(v) >= 4:
                _secrets.add(v)
                compact = v.replace(" ", "")
                if compact != v and len(compact) >= 4:
                    _secrets.add(compact)


def forget(value: str) -> None:
    with _lock:
        _secrets.discard(value)


def redact(text: str) -> str:
    if not text:
        return text
    with _lock:
        known = sorted(_secrets, key=len, reverse=True)
    for s in known:
        text = re.sub(re.escape(s), MASK, text, flags=re.I)
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def redact_obj(obj):
    """Recursively redact strings inside dicts/lists (for manifests and JSON evidence)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", "%H:%M:%S"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
