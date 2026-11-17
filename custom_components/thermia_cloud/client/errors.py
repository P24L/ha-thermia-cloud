"""Typed exceptions raised by the client."""

from __future__ import annotations


class ThermiaError(Exception):
    """Base class for all client errors."""


class AuthError(ThermiaError):
    """The cloud definitively rejected the credentials."""


class LoginFlowError(ThermiaError):
    """The login flow failed for another reason (changed HTML, B2C error, no code)."""


class PolicyAcceptanceError(LoginFlowError):
    """The account must accept new terms in the web app before login works."""


class NetworkError(ThermiaError):
    """Transport failure: DNS, connection, timeout."""


class ApiError(ThermiaError):
    """The API answered with an unexpected HTTP status."""

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(f"HTTP {status}{': ' + message if message else ''}")
        self.status = status


class RateLimitError(ApiError):
    """HTTP 429; ``retry_after`` is in seconds when the server said so."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__(429, "rate limited")
        self.retry_after = retry_after


class RegisterWriteError(ThermiaError):
    """A register write was rejected before or by the cloud."""


class RegisterValidationError(RegisterWriteError):
    """The value was refused locally (limits, step, visible values, read-only); nothing was sent."""
