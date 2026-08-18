"""Tile base types: result struct and `TileImpl` registration record.

Each concrete tile module defines:
  - DEFAULT_RGBA:   the diverse-mode default color
  - DEFAULT_PARAMS: dict of default parameter values
  - PARAM_RANGES:   dict of (min, max) tuples used during randomization
  - PARAM_DOCS:     one-line description per parameter, used to generate the
                    tile catalog in `docs/tiles.md`
  - emit(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params)
        -> TileEmitResult
  - surface_height(local_x, local_y, *, tile_size, **params) -> float

`emit` and `surface_height` are two views of the same geometry and MUST agree:
`emit` places it, `surface_height` answers "how high is the walkable surface at
this point in the tile". They live in the same module, next to each other, and
share the same span arithmetic, because keeping them in separate files is
exactly how they drifted apart before (the velocity map's copy was wrong for
four of the nine tiles). `tests/test_surface_contract.py` ray-casts the compiled
model and holds them to each other.

The registry dict lives in `myoassist_terrains.tiles.REGISTRY`; the composer
reaches it through `myoassist_terrains.registry.lookup`.
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
#
# It is also a hard floor on `base_height`: a tile whose base sits at or below
# BASELINE_Z has no room for geometry and is rejected by the tile (and by
# `composer._box_z_span` when connectors are negotiated).
BASELINE_Z: float = -2.0


@dataclass
class TileEmitResult:
    """What a tile reports back to the composer after emitting its geometry.

    `base_height`: z-coordinate at which the tile's edges sit. The composer uses
        it to negotiate connector heights with the neighbouring cells, so it must
        be the height the tile actually presents around its perimeter, not merely
        the value of a `base_height` parameter. Every tile satisfies the
        flat-at-base contract (`gap` excepted, which opens its trench mouth), so
        one value is sufficient.
    """

    base_height: float = 0.0


@dataclass
class TileImpl:
    """Registration record for a tile type."""

    type_name: str
    emit_fn: Callable[..., TileEmitResult]
    default_params: dict[str, Any]
    param_ranges: dict[str, tuple[float, float]]
    default_rgba: tuple[float, float, float, float]
    # Walkable-surface height at a tile-local (x, y). Paired with `emit_fn` and
    # required to agree with it; see the module docstring. Optional so a
    # third-party tile registered through `register_tile` can omit it, in which
    # case height queries fall back to the tile's `base_height` parameter.
    surface_height_fn: Callable[..., float] | None = None
    # Per-tile-type speed multiplier for the velocity map. Lives here rather
    # than in a module-level table in `velocity_map` so a custom tile can supply
    # one; `velocity_map.DEFAULT_SPEED_SCALE` is derived from these.
    default_speed_scale: float = 1.0
    # One-line description per parameter, keyed like `default_params`. Source for
    # the generated tile catalog, so the docs cannot drift from the code.
    param_docs: dict[str, str] = field(default_factory=dict)
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
