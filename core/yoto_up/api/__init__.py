"""Yoto API client layer -- re-exports the primary client class."""

from yoto_up.api.client import AuthenticationError, YotoClient

__all__ = ["AuthenticationError", "YotoClient"]
