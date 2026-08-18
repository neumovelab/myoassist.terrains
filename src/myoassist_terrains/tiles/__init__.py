"""Tile registry — maps tile type-name strings to their `TileImpl` records.

Adding a new tile type:
  1. Create `myoassist_terrains/tiles/<your_tile>.py` with DEFAULT_RGBA,
     DEFAULT_PARAMS, PARAM_RANGES, PARAM_DOCS, SPEED_SCALE, an `emit(...)`
     function and a `surface_height(...)` function, following the contract in
     `tiles/base.py`.
  2. Add it to the `_MODULES` tuple below.

We keep registration explicit (not import-time side effects) so the active
tile set is visible from one place. Each record is built from the module's own
declarations, so a tile cannot be registered with a height model or a speed
scale that belongs to a different tile.
"""

from __future__ import annotations

from types import ModuleType

from myoassist_terrains.tiles import (
    boulders,
    discrete_obstacles,
    flat,
    gap,
    pyramid_stairs,
    rough,
    slope,
    stairs,
    stepping_stones,
)
from myoassist_terrains.tiles.base import TileImpl


# (module, extra TileImpl overrides). Everything else is read off the module.
# spiral_stairs deferred to v2 (geometric complexity not justified for v1).
_MODULES: tuple[tuple[ModuleType, dict], ...] = (
    (flat, {}),
    (stairs, {"default_categorical": {"axis": ["x", "y"], "inverted": [False, True]}}),
    (pyramid_stairs, {"default_categorical": {"inverted": [False, True]}}),
    (slope, {"default_categorical": {"axis": ["x", "y"], "inverted": [False, True]}}),
    # `rough` overrides to a matte finish; built tiles use the default 0.5 shine.
    (rough, {"default_specular": 0.0, "default_shininess": 0.0}),
    (discrete_obstacles, {}),
    (stepping_stones, {}),
    (boulders, {}),
    (gap, {"default_categorical": {"axis": ["x", "y"]}}),
)


def _impl(module: ModuleType, **overrides) -> TileImpl:
    name = module.__name__.rsplit(".", 1)[-1]
    return TileImpl(
        type_name=name,
        emit_fn=module.emit,
        default_params=module.DEFAULT_PARAMS,
        param_ranges=module.PARAM_RANGES,
        default_rgba=module.DEFAULT_RGBA,
        surface_height_fn=module.surface_height,
        default_speed_scale=module.SPEED_SCALE,
        param_docs=module.PARAM_DOCS,
        **overrides,
    )


REGISTRY: dict[str, TileImpl] = {module.__name__.rsplit(".", 1)[-1]: _impl(module, **extra) for module, extra in _MODULES}


__all__ = ["REGISTRY"]
