"""Small shared helpers."""

from __future__ import annotations

import re

__all__ = ("natural_key",)

_DIGITS = re.compile(r"(\d+)")


def natural_key(text: str) -> list:
    """Sort key that orders ``Drone 2`` before ``Drone 10``."""
    return [int(part) if part.isdigit() else part.lower() for part in _DIGITS.split(text)]
