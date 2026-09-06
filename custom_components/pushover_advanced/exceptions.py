"""Exceptions for the Pushover Advanced integration."""
from __future__ import annotations


class PushoverError(Exception):
    """Base error for anything that goes wrong talking to Pushover."""


class PushoverAuthError(PushoverError):
    """Raised when the application token or user/group key is rejected."""


class PushoverRateLimitError(PushoverError):
    """Raised when the application's monthly message limit is exceeded."""


class PushoverApiError(PushoverError):
    """Raised for any other error response returned by the Pushover API."""

    def __init__(self, status: int, errors: list[str]) -> None:
        """Store the numeric status and the list of error strings."""
        self.status = status
        self.errors = errors
        super().__init__(f"Pushover API error (status={status}): {', '.join(errors) or 'unknown error'}")


class PushoverEncryptionError(PushoverError):
    """Raised when a message cannot be encrypted as requested."""
