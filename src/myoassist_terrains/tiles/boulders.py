"""`boulders` tile: scattered ellipsoid obstacles on a flat base.

Random ellipsoid geoms placed within the tile interior (with edge margin).
Each boulder has independently random radii along x, y, z drawn from
`size_range`. Boulders sit half-buried in the base slab so their visual
profile suggests rounded rocks rather than floating spheres — bottom-half
goes through the base, top-half protrudes.
"""

from __future__ import annotations

from functools import lru_cache

import mujoco as mj
import numpy as np

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.45, 0.45, 0.45, 1.0)  # dark gray

DEFAULT_PARAMS: dict = {
    "density": 0.3,  # boulders per m²
    "size_range": [0.20, 0.60],  # ellipsoid radius range (m); each axis sampled independently
    "edge_margin": 0.5,
    "seed": 0,
    "base_height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "density": (0.05, 0.8),
    "edge_margin": (0.2, 1.0),
    # base_height intentionally not randomized — see flat.py for the rationale.
}

PARAM_DOCS: dict[str, str] = {
    "density": "Boulders per square meter; the count is round(density * tile area).",
    "size_range": "Min and max ellipsoid RADIUS in meters, sampled independently per axis.",
    "edge_margin": "Keep boulder geometry this far inside the tile edge.",
    "seed": "RNG seed.",
    "base_height": "z-coordinate of the tile's flat-edge base.",
}

SPEED_SCALE = 0.32


@lru_cache(maxsize=64)
def _boulders(
    seed: int,
    density: float,
    size_lo: float,
    size_hi: float,
    edge_margin: float,
    tile_w: float,
    tile_l: float,
) -> tuple[tuple[float, float, float, float, float], ...]:
    """Replay the placement draws: one (x, y, rx, ry, rz) per boulder.

    `emit` and `surface_height` both read this, so the reported surface cannot
    disagree with the geometry. The draw order here IS the contract -- changing it
    changes every seeded layout. Cached because a velocity map samples one tile
    thousands of times.

    Placement is inset by `edge_margin` *plus the sampled radius*, so a boulder
    never crosses its own cell into the connector strip. Insetting only the centre
    let a default-configuration boulder overhang by up to 9 cm.
    """
    rng = np.random.default_rng(int(seed))
    count = max(1, int(round(density * tile_w * tile_l)))
    out = []
    for _ in range(count):
        # Radii first, so the inset can account for them; this fixes the draw
        # order relative to pre-1.0 layouts, which is unavoidable when the
        # placement bound depends on the size.
        rx = float(rng.uniform(size_lo, size_hi))
        ry = float(rng.uniform(size_lo, size_hi))
        rz = float(rng.uniform(size_lo, size_hi))
        half_x_inner = tile_w / 2 - edge_margin - rx
        half_y_inner = tile_l / 2 - edge_margin - ry
        if half_x_inner <= 0 or half_y_inner <= 0:
            raise ValueError(
                f"boulders: edge_margin {edge_margin:.3f} plus a sampled radius "
                f"({rx:.3f}, {ry:.3f}) leaves no room inside a {tile_w:.2f}x{tile_l:.2f} m tile; "
                f"reduce edge_margin or size_range."
            )
        x = float(rng.uniform(-half_x_inner, half_x_inner))
        y = float(rng.uniform(-half_y_inner, half_y_inner))
        out.append((x, y, rx, ry, rz))
    return tuple(out)


def surface_height(
    local_x: float,
    local_y: float,
    *,
    tile_size: tuple[float, float],
    density: float = 0.3,
    size_range=(0.20, 0.60),
    edge_margin: float = 0.5,
    seed: int = 0,
    base_height: float = 0.0,
    **_,
) -> float:
    """Walkable surface height: the top of any boulder covering (x, y), else base.

    Boulders are half-buried ellipsoids centred on `base_height`, so the exposed
    top at a point is `base + rz * sqrt(1 - (dx/rx)^2 - (dy/ry)^2)`.
    """
    size_range = tuple(size_range)
    top = float(base_height)
    for bx, by, rx, ry, rz in _boulders(
        int(seed), float(density), float(size_range[0]), float(size_range[1]),
        float(edge_margin), float(tile_size[0]), float(tile_size[1])
    ):
        nx = (local_x - bx) / rx
        ny = (local_y - by) / ry
        radial = nx * nx + ny * ny
        if radial < 1.0:
            top = max(top, float(base_height) + rz * float(np.sqrt(1.0 - radial)))
    return top


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
) -> TileEmitResult:
    if density <= 0:
        raise ValueError(f"boulders.density must be > 0 (got {density})")
    size_range = tuple(size_range)
    if size_range[0] <= 0 or size_range[1] < size_range[0]:
        raise ValueError(f"size_range must be (min>0, max>=min); got {size_range}")
    if edge_margin < 0:
        raise ValueError(f"boulders.edge_margin must be >= 0 (got {edge_margin})")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"boulders '{name}': base top z={base_top_z:.3f} <= BASELINE_Z={BASELINE_Z:.3f}; increase base_height."
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

    # 2. Half-buried ellipsoid boulders, placed by the shared draw so
    #    `surface_height` reports exactly this geometry.
    try:
        placement = _boulders(
            int(seed), float(density), float(size_range[0]), float(size_range[1]),
            float(edge_margin), float(tile_size[0]), float(tile_size[1])
        )
    except ValueError as exc:
        raise ValueError(f"boulders '{name}': {exc}") from exc

    for i, (local_x, local_y, rx, ry, rz) in enumerate(placement):
        # Position the boulder so its center is AT base_top_z — bottom half
        # is buried in the base slab, top half protrudes.
        spec.worldbody.add_geom(
            name=f"{name}_rock_{i}",
            size=[rx, ry, rz],
            pos=[origin_x + local_x, origin_y + local_y, base_top_z],
            **boulder_geom_kwargs,
        )

    return TileEmitResult(base_height=base_height)
