"""`discrete_obstacles` tile: scattered box-extrusion obstacles on a flat base.

Random box geoms placed within the tile interior. Each obstacle is a small
upright box; positions are uniform within an inset region so obstacles
don't crowd the tile edges. The base slab covers the full tile at
`base_height` so the boundary contract holds.

`density` is in obstacles per square meter; the actual count is rounded
from `density * tile_area`.
"""

from __future__ import annotations

from functools import lru_cache

import mujoco as mj
import numpy as np

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.75, 0.35, 0.30, 1.0)  # muted red

DEFAULT_PARAMS: dict = {
    "density": 0.4,  # obstacles per m²
    "size_range": [0.20, 0.50],  # box footprint side length range (m)
    "height_range": [0.10, 0.40],  # obstacle height range above base (m)
    "edge_margin": 0.5,  # don't place obstacles within this distance of tile edges
    "seed": 0,
    "base_height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "density": (0.1, 1.0),
    "edge_margin": (0.2, 1.0),
    # base_height intentionally not randomized — see flat.py for the rationale.
}

PARAM_DOCS: dict[str, str] = {
    "density": "Obstacles per square meter; the count is round(density * tile area).",
    "size_range": "Min and max obstacle footprint side length in meters.",
    "height_range": "Min and max obstacle height above base in meters.",
    "edge_margin": "Keep obstacle geometry this far inside the tile edge.",
    "seed": "RNG seed.",
    "base_height": "z-coordinate of the tile's flat-edge base.",
}

SPEED_SCALE = 0.38


@lru_cache(maxsize=64)
def _obstacles(
    seed: int,
    density: float,
    size_lo: float,
    size_hi: float,
    height_lo: float,
    height_hi: float,
    edge_margin: float,
    tile_w: float,
    tile_l: float,
) -> tuple[tuple[float, float, float, float, float], ...]:
    """Replay the placement draws: one (x, y, half_x, half_y, height) per obstacle.

    Shared by `emit` and `surface_height` so the reported surface cannot disagree
    with the geometry. Placement is inset by `edge_margin` plus the sampled half
    footprint, so an obstacle never crosses its own cell.
    """
    rng = np.random.default_rng(int(seed))
    count = max(1, int(round(density * tile_w * tile_l)))
    out = []
    for _ in range(count):
        half_x = float(rng.uniform(size_lo, size_hi)) / 2
        half_y = float(rng.uniform(size_lo, size_hi)) / 2
        height = float(rng.uniform(height_lo, height_hi))
        limit_x = tile_w / 2 - edge_margin - half_x
        limit_y = tile_l / 2 - edge_margin - half_y
        if limit_x <= 0 or limit_y <= 0:
            raise ValueError(
                f"edge_margin {edge_margin:.3f} plus a sampled half-footprint "
                f"({half_x:.3f}, {half_y:.3f}) leaves no room inside a "
                f"{tile_w:.2f}x{tile_l:.2f} m tile; reduce edge_margin or size_range."
            )
        x = float(rng.uniform(-limit_x, limit_x))
        y = float(rng.uniform(-limit_y, limit_y))
        out.append((x, y, half_x, half_y, height))
    return tuple(out)


def surface_height(
    local_x: float,
    local_y: float,
    *,
    tile_size: tuple[float, float],
    density: float = 0.4,
    size_range=(0.20, 0.50),
    height_range=(0.10, 0.40),
    edge_margin: float = 0.5,
    seed: int = 0,
    base_height: float = 0.0,
    **_,
) -> float:
    """Walkable surface height: the top of any obstacle covering (x, y), else base."""
    size_range, height_range = tuple(size_range), tuple(height_range)
    top = float(base_height)
    for ox, oy, half_x, half_y, height in _obstacles(
        int(seed),
        float(density),
        float(size_range[0]),
        float(size_range[1]),
        float(height_range[0]),
        float(height_range[1]),
        float(edge_margin),
        float(tile_size[0]),
        float(tile_size[1]),
    ):
        if abs(local_x - ox) <= half_x and abs(local_y - oy) <= half_y:
            top = max(top, float(base_height) + height)
    return top


def emit(
    spec: mj.MjSpec,
    origin_xyz: tuple[float, float, float],
    name: str,
    *,
    tile_size: tuple[float, float],
    rgba: tuple[float, float, float, float] | None = None,
    material: str | None = None,
    density: float = 0.4,
    size_range: tuple[float, float] = (0.20, 0.50),
    height_range: tuple[float, float] = (0.10, 0.40),
    edge_margin: float = 0.5,
    seed: int = 0,
    base_height: float = 0.0,
) -> TileEmitResult:
    if density <= 0:
        raise ValueError(f"discrete_obstacles.density must be > 0 (got {density})")
    size_range = tuple(size_range)
    height_range = tuple(height_range)
    if size_range[0] <= 0 or size_range[1] < size_range[0]:
        raise ValueError(f"size_range must be (min>0, max>=min); got {size_range}")
    if height_range[0] <= 0 or height_range[1] < height_range[0]:
        raise ValueError(f"height_range must be (min>0, max>=min); got {height_range}")
    if edge_margin < 0:
        raise ValueError(f"discrete_obstacles.edge_margin must be >= 0 (got {edge_margin})")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"discrete_obstacles '{name}': base top z={base_top_z:.3f} <= BASELINE_Z={BASELINE_Z:.3f}; increase base_height."
        )

    origin_x, origin_y = origin_xyz[0], origin_xyz[1]

    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_BOX,
        "contype": 1,
        "conaffinity": 1,
    }
    if material is not None:
        geom_kwargs["material"] = material
    if rgba is not None:
        geom_kwargs["rgba"] = list(rgba)

    # 1. Base slab.
    base_half_z = (base_top_z - BASELINE_Z) / 2
    base_center_z = (base_top_z + BASELINE_Z) / 2
    spec.worldbody.add_geom(
        name=f"{name}_base",
        size=[tile_size[0] / 2, tile_size[1] / 2, base_half_z],
        pos=[origin_x, origin_y, base_center_z],
        **geom_kwargs,
    )

    # 2. Scattered obstacles, placed by the shared draw so `surface_height`
    #    reports exactly this geometry.
    try:
        placement = _obstacles(
            int(seed),
            float(density),
            float(size_range[0]),
            float(size_range[1]),
            float(height_range[0]),
            float(height_range[1]),
            float(edge_margin),
            float(tile_size[0]),
            float(tile_size[1]),
        )
    except ValueError as exc:
        raise ValueError(f"discrete_obstacles '{name}': {exc}") from exc

    for i, (local_x, local_y, sx, sy, h) in enumerate(placement):
        spec.worldbody.add_geom(
            name=f"{name}_obs_{i}",
            size=[sx, sy, h / 2],
            pos=[origin_x + local_x, origin_y + local_y, base_top_z + h / 2],
            **geom_kwargs,
        )

    return TileEmitResult(base_height=base_height)
