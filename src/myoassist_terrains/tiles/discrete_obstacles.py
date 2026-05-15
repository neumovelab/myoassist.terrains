"""`discrete_obstacles` tile: scattered box-extrusion obstacles on a flat base.

Random box geoms placed within the tile interior. Each obstacle is a small
upright box; positions are uniform within an inset region so obstacles
don't crowd the tile edges. The base slab covers the full tile at
`base_height` so the boundary contract holds.

`density` is in obstacles per square meter; the actual count is rounded
from `density * tile_area`.
"""

from __future__ import annotations

import mujoco as mj
import numpy as np

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.75, 0.35, 0.30, 1.0)  # muted red

DEFAULT_PARAMS: dict = {
    "density": 0.4,         # obstacles per m²
    "size_range": [0.20, 0.50],   # box footprint side length range (m)
    "height_range": [0.10, 0.40], # obstacle height range above base (m)
    "edge_margin": 0.5,     # don't place obstacles within this distance of tile edges
    "seed": 0,
    "base_height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "density": (0.1, 1.0),
    "edge_margin": (0.2, 1.0),
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
    density: float = 0.4,
    size_range: tuple[float, float] = (0.20, 0.50),
    height_range: tuple[float, float] = (0.10, 0.40),
    edge_margin: float = 0.5,
    seed: int = 0,
    base_height: float = 0.0,
    output_dir=None,
    terrain_name=None,
) -> TileEmitResult:
    if density <= 0:
        raise ValueError(f"discrete_obstacles.density must be > 0 (got {density})")
    size_range = tuple(size_range)
    height_range = tuple(height_range)
    if size_range[0] <= 0 or size_range[1] < size_range[0]:
        raise ValueError(f"size_range must be (min>0, max>=min); got {size_range}")
    if height_range[0] <= 0 or height_range[1] < height_range[0]:
        raise ValueError(f"height_range must be (min>0, max>=min); got {height_range}")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"discrete_obstacles '{name}': base top z={base_top_z:.3f} <= "
            f"BASELINE_Z={BASELINE_Z:.3f}; increase base_height."
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

    # 2. Scattered obstacles.
    rng = np.random.default_rng(int(seed))
    n_obstacles = max(1, int(round(density * tile_size[0] * tile_size[1])))

    half_x_inner = tile_size[0] / 2 - edge_margin
    half_y_inner = tile_size[1] / 2 - edge_margin
    if half_x_inner <= 0 or half_y_inner <= 0:
        raise ValueError(
            f"discrete_obstacles '{name}': edge_margin {edge_margin:.3f} too large for tile"
        )

    for i in range(n_obstacles):
        local_x = float(rng.uniform(-half_x_inner, half_x_inner))
        local_y = float(rng.uniform(-half_y_inner, half_y_inner))
        sx = float(rng.uniform(*size_range)) / 2
        sy = float(rng.uniform(*size_range)) / 2
        h = float(rng.uniform(*height_range))
        spec.worldbody.add_geom(
            name=f"{name}_obs_{i}",
            size=[sx, sy, h / 2],
            pos=[origin_x + local_x, origin_y + local_y, base_top_z + h / 2],
            **geom_kwargs,
        )

    return TileEmitResult(base_height=base_height)
