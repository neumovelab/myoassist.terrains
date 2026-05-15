"""`stepping_stones` tile: regular grid of raised stones on a flat base.

Stones are arranged in a `rows × cols` grid centered on the tile, each
stone optionally jittered within its cell by a fraction of the cell size.
Stones are rendered as upright boxes a configurable height above the base.

The base slab spans the full tile at `base_height` so the model can walk
between stones without falling through. (For "true" stepping stones with
gaps the model must bridge, the base slab can be removed in v2 — for v1
this design behaves more like "regular discrete bumps" but is simpler and
still demands stepping behavior.)
"""

from __future__ import annotations

import mujoco as mj
import numpy as np

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.55, 0.45, 0.65, 1.0)  # muted purple

DEFAULT_PARAMS: dict = {
    "rows": 4,
    "cols": 4,
    "stone_size": 0.6,    # stone footprint side length (m)
    "stone_height": 0.20, # stone height above base (m)
    "jitter_frac": 0.20,  # random offset as fraction of cell size
    "edge_margin": 0.5,   # leave a flat margin around the stones
    "seed": 0,
    "base_height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "rows": (2, 8),
    "cols": (2, 8),
    "stone_size": (0.30, 1.00),
    "stone_height": (0.05, 0.40),
    "jitter_frac": (0.0, 0.40),
    # base_height intentionally not randomized — see flat.py for the rationale.
}


def emit(
    spec: mj.MjSpec,
    origin_xyz: tuple[float, float, float],
    name: str,
    *,
    tile_size: tuple[float, float],
    rgba: tuple[float, float, float, float] | None = None,
    material: str | None = None,
    rows: int = 4,
    cols: int = 4,
    stone_size: float = 0.6,
    stone_height: float = 0.20,
    jitter_frac: float = 0.20,
    edge_margin: float = 0.5,
    seed: int = 0,
    base_height: float = 0.0,
    output_dir=None,
    terrain_name=None,
) -> TileEmitResult:
    if rows < 1 or cols < 1:
        raise ValueError(f"rows and cols must be >= 1 (got {rows}, {cols})")
    if stone_size <= 0 or stone_height <= 0:
        raise ValueError("stone_size and stone_height must be positive")
    if not (0.0 <= jitter_frac <= 0.49):
        raise ValueError(f"jitter_frac must be in [0, 0.49] (got {jitter_frac})")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"stepping_stones '{name}': base top z={base_top_z:.3f} <= "
            f"BASELINE_Z={BASELINE_Z:.3f}; increase base_height."
        )

    origin_x, origin_y = origin_xyz[0], origin_xyz[1]
    inner_w = tile_size[0] - 2 * edge_margin
    inner_l = tile_size[1] - 2 * edge_margin
    if inner_w <= 0 or inner_l <= 0:
        raise ValueError(
            f"stepping_stones '{name}': edge_margin {edge_margin:.3f} too large for tile"
        )

    cell_w = inner_w / cols
    cell_l = inner_l / rows
    if stone_size >= min(cell_w, cell_l):
        raise ValueError(
            f"stepping_stones '{name}': stone_size {stone_size:.3f} >= cell size "
            f"({cell_w:.3f} × {cell_l:.3f}); reduce stone_size, rows, or cols."
        )

    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_BOX,
        "contype": 1,
        "conaffinity": 1,
    }
    if material is not None:
        geom_kwargs["material"] = material
    if rgba is not None:
        geom_kwargs["rgba"] = list(rgba)

    # 1. Base slab spanning the full tile.
    base_half_z = (base_top_z - BASELINE_Z) / 2
    base_center_z = (base_top_z + BASELINE_Z) / 2
    spec.worldbody.add_geom(
        name=f"{name}_base",
        size=[tile_size[0] / 2, tile_size[1] / 2, base_half_z],
        pos=[origin_x, origin_y, base_center_z],
        **geom_kwargs,
    )

    # 2. Stones on a regular grid with optional jitter.
    rng = np.random.default_rng(int(seed))
    half_stone = stone_size / 2

    # Centers of the cells in tile-local frame.
    x0 = -inner_w / 2 + cell_w / 2
    y0 = -inner_l / 2 + cell_l / 2
    max_jitter_x = jitter_frac * cell_w
    max_jitter_y = jitter_frac * cell_l

    stone_idx = 0
    for r in range(rows):
        for c in range(cols):
            local_x = x0 + c * cell_w + float(rng.uniform(-max_jitter_x, max_jitter_x))
            local_y = y0 + r * cell_l + float(rng.uniform(-max_jitter_y, max_jitter_y))
            spec.worldbody.add_geom(
                name=f"{name}_stone_{stone_idx}",
                size=[half_stone, half_stone, stone_height / 2],
                pos=[origin_x + local_x, origin_y + local_y, base_top_z + stone_height / 2],
                **geom_kwargs,
            )
            stone_idx += 1

    return TileEmitResult(base_height=base_height)
