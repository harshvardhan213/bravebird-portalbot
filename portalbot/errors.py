"""Two kinds of failure: retryable ones get another attempt, final ones stop the run."""
from __future__ import annotations


class RetryableError(Exception):
    """Transient: a timeout, a slow page, a network blip. Trying again may work."""


class FinalError(Exception):
    """Trying again won't help: wrong password, rejected code, element not on the page."""


class LoginFailed(FinalError):
    pass


class CodeRejected(FinalError):
    pass


class UnexpectedPage(FinalError):
    pass
