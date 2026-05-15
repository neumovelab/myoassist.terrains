"""Tile registry — maps tile type-name strings to their `TileImpl` records.

Adding a new tile type:
  1. Create `myoassist_terrains/tiles/<your_tile>.py` with DEFAULT_RGBA,
     DEFAULT_PARAMS, PARAM_RANGES, and an `emit(...)` function that follows
     the contract in `tiles/base.py`.
  2. Import it here and add an entry to the REGISTRY dict below.

We keep registration explicit (not import-time side effects) so the active
tile set is visible from one place.
"""

from __future__ import annotations

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


REGISTRY: dict[str, TileImpl] = {
    "flat": TileImpl(
        type_name="flat",
        emit_fn=flat.emit,
        default_params=flat.DEFAULT_PARAMS,
        param_ranges=flat.PARAM_RANGES,
        default_rgba=flat.DEFAULT_RGBA,
    ),
    "stairs": TileImpl(
        type_name="stairs",
        emit_fn=stairs.emit,
        default_params=stairs.DEFAULT_PARAMS,
        param_ranges=stairs.PARAM_RANGES,
        default_rgba=stairs.DEFAULT_RGBA,
        default_categorical={"axis": ["x", "y"], "inverted": [False, True]},
    ),
    "pyramid_stairs": TileImpl(
        type_name="pyramid_stairs",
        emit_fn=pyramid_stairs.emit,
        default_params=pyramid_stairs.DEFAULT_PARAMS,
        param_ranges=pyramid_stairs.PARAM_RANGES,
        default_rgba=pyramid_stairs.DEFAULT_RGBA,
        default_categorical={"inverted": [False, True]},
    ),
    "slope": TileImpl(
        type_name="slope",
        emit_fn=slope.emit,
        default_params=slope.DEFAULT_PARAMS,
        param_ranges=slope.PARAM_RANGES,
        default_rgba=slope.DEFAULT_RGBA,
        default_categorical={"axis": ["x", "y"], "inverted": [False, True]},
    ),
    "rough": TileImpl(
        type_name="rough",
        emit_fn=rough.emit,
        default_params=rough.DEFAULT_PARAMS,
        param_ranges=rough.PARAM_RANGES,
        default_rgba=rough.DEFAULT_RGBA,
        default_specular=0.0,  # natural matte look; built tiles use the default 0.5 shine
        default_shininess=0.0,
    ),
    "discrete_obstacles": TileImpl(
        type_name="discrete_obstacles",
        emit_fn=discrete_obstacles.emit,
        default_params=discrete_obstacles.DEFAULT_PARAMS,
        param_ranges=discrete_obstacles.PARAM_RANGES,
        default_rgba=discrete_obstacles.DEFAULT_RGBA,
    ),
    "stepping_stones": TileImpl(
        type_name="stepping_stones",
        emit_fn=stepping_stones.emit,
        default_params=stepping_stones.DEFAULT_PARAMS,
        param_ranges=stepping_stones.PARAM_RANGES,
        default_rgba=stepping_stones.DEFAULT_RGBA,
    ),
    "boulders": TileImpl(
        type_name="boulders",
        emit_fn=boulders.emit,
        default_params=boulders.DEFAULT_PARAMS,
        param_ranges=boulders.PARAM_RANGES,
        default_rgba=boulders.DEFAULT_RGBA,
    ),
    "gap": TileImpl(
        type_name="gap",
        emit_fn=gap.emit,
        default_params=gap.DEFAULT_PARAMS,
        param_ranges=gap.PARAM_RANGES,
        default_rgba=gap.DEFAULT_RGBA,
        default_categorical={"axis": ["x", "y"]},
    ),
    # spiral_stairs deferred to v2 (geometric complexity not justified for v1).
}


__all__ = ["REGISTRY"]
