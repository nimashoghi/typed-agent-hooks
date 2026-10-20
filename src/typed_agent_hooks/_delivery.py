"""Dispatch-local transport metadata, separate from provider wire input."""

from contextvars import ContextVar

response_available: ContextVar[bool] = ContextVar("hook_response_available", default=True)
