"""Tile base types: result struct and `TileImpl` registration record.

Each concrete tile module defines:
  - DEFAULT_RGBA: the diverse-mode default color
  - DEFAULT_PARAMS: dict of default parameter values
  - PARAM_RANGES:   dict of (min, max) tuples used during randomization (M5)
  - emit(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params) -> TileEmitResult

The composer looks tiles up via `myoassist_terrains.registry.REGISTRY` (a dict
populated in `myoassist_terrains.tiles.__init__`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


Side = Literal["n", "s", "e", "w"]


# Shared baseline z. Every tile's box bottoms out here; the tile's `height`
# parameter only sets its TOP face. The depth (|BASELINE_Z|) sets how far
# below the surface tile geometry can extend — inverted (downward) variants
# of stairs / slope / pyramid_stairs need their pit floors to stay above
# BASELINE_Z, so this is set generous enough to allow ~2 m of descent
# before the user has to override.
BASELINE_Z: float = -2.0


@dataclass
class TileEmitResult:
    """What a tile reports back to the composer after emitting its geometry.

    `base_height`: z-coordinate at which the tile's edges sit. Used by the
        composer to decide connector heights between adjacent tiles. In v1
        every tile presents flat-at-base edges, so this single value is
        sufficient; v2 may extend with per-side heights via
        `boundary_heights`.

    `boundary_heights`: optional override mapping side -> height, for v2.
        v1 tiles can leave this unset.
    """

    base_height: float = 0.0
    boundary_heights: dict[Side, float] = field(default_factory=dict)


@dataclass
class TileImpl:
    """Registration record for a tile type."""

    type_name: str
    emit_fn: Callable[..., TileEmitResult]
    default_params: dict[str, Any]
    param_ranges: dict[str, tuple[float, float]]
    default_rgba: tuple[float, float, float, float]
    # Material specular / shininess applied when the tile is rendered via
    # diverse/custom palette mode. MuJoCo's `reflectance` only works for a
    # single reflective surface in the scene, so for multi-tile terrain we
    # use specular highlights (Phong shading) which apply to every geom.
    # Natural tiles (e.g. `rough`) override to 0 for a matte finish.
    default_specular: float = 0.5
    default_shininess: float = 0.5
    # Categorical params to randomize by default (e.g. {'axis': ['x', 'y']}).
    # Sampled uniformly from the supplied list whenever this tile is chosen
    # in randomization mode. User can override via param_ranges.
    default_categorical: dict[str, list] = field(default_factory=dict)
