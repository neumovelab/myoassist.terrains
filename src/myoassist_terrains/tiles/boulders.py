"""`boulders` tile: scattered ellipsoid obstacles on a flat base.

Random ellipsoid geoms placed within the tile interior (with edge margin).
Each boulder has independently random radii along x, y, z drawn from
`size_range`. Boulders sit half-buried in the base slab so their visual
profile suggests rounded rocks rather than floating spheres — bottom-half
goes through the base, top-half protrudes.
"""

from __future__ import annotations

import mujoco as mj
import numpy as np

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.45, 0.45, 0.45, 1.0)  # dark gray

DEFAULT_PARAMS: dict = {
    "density": 0.3,           # boulders per m²
    "size_range": [0.20, 0.60], # ellipsoid radius range (m); each axis sampled independently
    "edge_margin": 0.5,
    "seed": 0,
    "base_height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "density": (0.05, 0.8),
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
    density: float = 0.3,
    size_range: tuple[float, float] = (0.20, 0.60),
    edge_margin: float = 0.5,
    seed: int = 0,
    base_height: float = 0.0,
    output_dir=None,
    terrain_name=None,
) -> TileEmitResult:
    if density <= 0:
        raise ValueError(f"boulders.density must be > 0 (got {density})")
    size_range = tuple(size_range)
    if size_range[0] <= 0 or size_range[1] < size_range[0]:
        raise ValueError(f"size_range must be (min>0, max>=min); got {size_range}")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"boulders '{name}': base top z={base_top_z:.3f} <= "
            f"BASELINE_Z={BASELINE_Z:.3f}; increase base_height."
        )

    origin_x, origin_y = origin_xyz[0], origin_xyz[1]

    base_geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_BOX,
        "contype": 1,
        "conaffinity": 1,
    }
    boulder_geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_ELLIPSOID,
        "contype": 1,
        "conaffinity": 1,
    }
    if material is not None:
        base_geom_kwargs["material"] = material
        boulder_geom_kwargs["material"] = material
    if rgba is not None:
        base_geom_kwargs["rgba"] = list(rgba)
        boulder_geom_kwargs["rgba"] = list(rgba)

    # 1. Base slab spanning the full tile.
    base_half_z = (base_top_z - BASELINE_Z) / 2
    base_center_z = (base_top_z + BASELINE_Z) / 2
    spec.worldbody.add_geom(
        name=f"{name}_base",
        size=[tile_size[0] / 2, tile_size[1] / 2, base_half_z],
        pos=[origin_x, origin_y, base_center_z],
        **base_geom_kwargs,
    )

    # 2. Half-buried ellipsoid boulders.
    rng = np.random.default_rng(int(seed))
    n_boulders = max(1, int(round(density * tile_size[0] * tile_size[1])))

    half_x_inner = tile_size[0] / 2 - edge_margin
    half_y_inner = tile_size[1] / 2 - edge_margin
    if half_x_inner <= 0 or half_y_inner <= 0:
        raise ValueError(
            f"boulders '{name}': edge_margin {edge_margin:.3f} too large for tile"
        )

    for i in range(n_boulders):
        local_x = float(rng.uniform(-half_x_inner, half_x_inner))
        local_y = float(rng.uniform(-half_y_inner, half_y_inner))
        rx = float(rng.uniform(*size_range))
        ry = float(rng.uniform(*size_range))
        rz = float(rng.uniform(*size_range))
        # Position the boulder so its center is AT base_top_z — bottom half
        # is buried in the base slab, top half protrudes.
        spec.worldbody.add_geom(
            name=f"{name}_rock_{i}",
            size=[rx, ry, rz],
            pos=[origin_x + local_x, origin_y + local_y, base_top_z],
            **boulder_geom_kwargs,
        )

    return TileEmitResult(base_height=base_height)
