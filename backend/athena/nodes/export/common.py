"""Small helpers for writing export templates."""
from __future__ import annotations

from typing import Any, Callable

Template = Callable[[dict[str, Any]], str]


def items(text: str) -> list[str]:
    """'a, b,c' -> ['a', 'b', 'c']"""
    return [p.strip() for p in str(text).split(",") if p.strip()]


def lines(*parts: str) -> str:
    return "\n".join(p for p in parts if p) + "\n"
