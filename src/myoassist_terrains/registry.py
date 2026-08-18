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
    surface_height: Callable[..., float] | None = None,
    speed_scale: float = 1.0,
    param_docs: dict[str, str] | None = None,
) -> None:
    """Add (or overwrite) a tile type in the registry. Useful for plugins.

    `surface_height(local_x, local_y, *, tile_size, **params) -> float` reports
    the walkable surface height at a tile-local coordinate. Supply it so the
    velocity map, and any consumer asking `surface_height_at` where the ground
    is, describe your tile correctly; omit it and those queries fall back to the
    tile's `base_height` parameter, which is only right for a flat-topped tile.

    `speed_scale` is the velocity map's per-tile-type speed multiplier (1.0 is
    flat-terrain speed). Without it a custom tile would have no entry and the
    velocity map could not size its arrows.

    `param_docs` maps parameter name -> one-line description. Only used to
    generate documentation, so it is optional.
    """
    REGISTRY[type_name] = TileImpl(
        type_name=type_name,
        emit_fn=emit_fn,
        default_params=default_params or {},
        param_ranges=param_ranges or {},
        default_rgba=default_rgba,
        surface_height_fn=surface_height,
        default_speed_scale=float(speed_scale),
        param_docs=param_docs or {},
    )
