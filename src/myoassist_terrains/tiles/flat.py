"""`flat` tile: a single thin box geom occupying the cell.

The top face sits at `origin_z + height`; the box has fixed thickness so the
geometry hangs below the walkable surface. All four edges of the cell are at
the declared height — boundary contract is flat-at-base.
"""

from __future__ import annotations

import mujoco as mj

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.78, 0.78, 0.78, 1.0)

DEFAULT_PARAMS: dict = {
    "height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    # `height` deliberately omitted from default randomization: leaving it
    # fixed at the DEFAULT_PARAMS value keeps adjacent randomized tiles at
    # the same base level (clean connector edges). Users who want flat-tile
    # height variation can opt in via randomization.param_ranges in their
    # config.
}

PARAM_DOCS: dict[str, str] = {
    "height": "Top face z-coordinate (offset above the grid plane).",
}

SPEED_SCALE = 1.00


def surface_height(_local_x: float, _local_y: float, *, height: float = 0.0, **_) -> float:
    """Walkable surface height. The whole tile top sits at `height`."""
    return float(height)


def emit(
    spec: mj.MjSpec,
    origin_xyz: tuple[float, float, float],
    name: str,
    *,
    tile_size: tuple[float, float],
    rgba: tuple[float, float, float, float] | None = None,
    material: str | None = None,
    height: float = 0.0,
    output_dir=None,  # unused; accepted for uniform composer API
    terrain_name=None,  # unused; accepted for uniform composer API
) -> TileEmitResult:
    """Emit a flat tile centered at (origin_x, origin_y) with top face at origin_z + height.

    Bottom face is at BASELINE_Z; box thickness varies with height so all
    tiles share a common floor and adjacent height differences become clean
    step risers rather than floating shelves.
    """
    x, y, z = origin_xyz
    half_w = tile_size[0] / 2
    half_l = tile_size[1] / 2

    top_z = z + height
    bottom_z = BASELINE_Z
    if top_z <= bottom_z:
        raise ValueError(
            f"flat tile {name!r} has top z={top_z:.3f} <= BASELINE_Z={bottom_z:.3f}; "
            f"`height` must satisfy origin_z + height > BASELINE_Z. "
            f"For tiles meant to dip below baseline, use a `gap` tile (M4)."
        )
    half_z = (top_z - bottom_z) / 2
    center_z = (top_z + bottom_z) / 2

    # Static terrain: emit geom directly on worldbody (no intermediate body),
    # so MuJoCo treats the geom as fixed and no body inertia is computed.
    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_BOX,
        "size": [half_w, half_l, half_z],
        "pos": [x, y, center_z],
        "contype": 1,
        "conaffinity": 1,
    }
    if material is not None:
        geom_kwargs["material"] = material
    if rgba is not None:
        geom_kwargs["rgba"] = list(rgba)

    spec.worldbody.add_geom(name=f"{name}_box", **geom_kwargs)

    return TileEmitResult(base_height=height)
