"""Public registry helpers — lookup and external registration.

The actual tile dict lives in `myoassist_terrains.tiles.REGISTRY`. This module
exposes a small public surface (`lookup`, `register_tile`) so consumer code
can extend the tile set without reaching into the tiles subpackage.
"""

from __future__ import annotations

from typing import Any, Callable

from myoassist_terrains.tiles import REGISTRY
from myoassist_terrains.tiles.base import TileEmitResult, TileImpl


def lookup(type_name: str) -> TileImpl:
    """Return the TileImpl for a registered type, raising KeyError if unknown."""
    if type_name not in REGISTRY:
        raise KeyError(f"Unknown tile type {type_name!r}. Registered: {sorted(REGISTRY)}")
    return REGISTRY[type_name]


def register_tile(
    type_name: str,
    emit_fn: Callable[..., TileEmitResult],
    *,
    default_params: dict[str, Any] | None = None,
    param_ranges: dict[str, tuple[float, float]] | None = None,
    default_rgba: tuple[float, float, float, float] = (0.78, 0.78, 0.78, 1.0),
) -> None:
    """Add (or overwrite) a tile type in the registry. Useful for plugins."""
    REGISTRY[type_name] = TileImpl(
        type_name=type_name,
        emit_fn=emit_fn,
        default_params=default_params or {},
        param_ranges=param_ranges or {},
        default_rgba=default_rgba,
    )
