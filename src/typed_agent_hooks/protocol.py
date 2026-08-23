"""Versioned private description exchanged by hook executables and collections."""

from typing import Literal

from .config import ProviderName
from .core import StrictModel


class AppDescription(StrictModel):
    """Provider configs rendered by one executable hook application."""

    protocol: Literal[1] = 1
    name: str
    providers: tuple[ProviderName, ...]
    configs: dict[ProviderName, dict[str, object]]
