"""`rough` tile: hfield-based naturalistic terrain.

Generates a per-tile heightmap PNG via the fractal-composite noise
generator (see `myoassist_terrains.noise`), declares an `<asset><hfield/>` for it,
and emits a single hfield geom that occupies the tile.

The heightmap is edge-tapered so its values are 0 at the boundary, which
puts the hfield surface at `base_height` along the perimeter — same
flat-at-base contract as the other tiles.

Hfield geometry mapping (MuJoCo `size` = `(half_x, half_y, max_z, base_z)`):
- half_x, half_y: full tile half-extents
- max_z = `vertical_relief`: heightmap value 1.0 reaches base_height + vertical_relief
- base_z = base_height − BASELINE_Z: hfield base extends down to BASELINE_Z

PNG file path emitted into the XML uses a `../terrain/<file>.png` prefix
because MuJoCo resolves nested-include asset paths relative to the
top-level model file's directory (one level above `model/terrain/`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import mujoco as mj
import numpy as np
from PIL import Image

from myoassist_terrains.noise import edge_taper, generate_complex_terrain
from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.55, 0.45, 0.35, 1.0)  # warm brown

DEFAULT_PARAMS: dict = {
    "seed": 0,
    "vertical_relief": 0.8,
    "grid_resolution": 256,
    "num_pits": 18,
    "num_hills": 24,
    "terrace_levels": 5,
    "pit_threshold": 0.33,
    "plateau_threshold": 0.68,
    "edge_taper_frac": 0.10,
    "base_height": 0.0,
    # How vertical_relief is distributed around base_height:
    #   "centered" (default) — features oscillate ±vertical_relief/2 around
    #     base_height. Edges land exactly at base_height, so seams are
    #     smooth and the rough surface has both bumps and pits.
    #   "up"   — edges at base_height, features rise above by up to
    #     vertical_relief.
    #   "down" — edges at base_height, features dip below by up to
    #     vertical_relief.
    "relief_mode": "centered",
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "seed": (0, 1_000_000),
    "vertical_relief": (0.1, 1.5),
    "num_pits": (0, 30),
    "num_hills": (0, 30),
    "terrace_levels": (1, 9),
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
    output_dir: Optional[Path] = None,
    terrain_name: Optional[str] = None,
    asset_path_prefix: str = "../terrain",
    seed: int = 0,
    vertical_relief: float = 0.8,
    grid_resolution: int = 256,
    num_pits: int = 18,
    num_hills: int = 24,
    terrace_levels: int = 5,
    pit_threshold: float = 0.33,
    plateau_threshold: float = 0.68,
    edge_taper_frac: float = 0.10,
    base_height: float = 0.0,
    relief_mode: str = "centered",
) -> TileEmitResult:
    if output_dir is None:
        raise ValueError(
            f"rough tile {name!r} requires `output_dir` to write its hfield PNG; "
            f"the composer should pass this automatically."
        )
    if vertical_relief <= 0:
        raise ValueError(f"rough.vertical_relief must be > 0 (got {vertical_relief})")
    if grid_resolution < 8:
        raise ValueError(f"rough.grid_resolution must be >= 8 (got {grid_resolution})")
    if not (0.0 <= edge_taper_frac < 0.5):
        raise ValueError(
            f"rough.edge_taper_frac must satisfy 0 <= frac < 0.5 (got {edge_taper_frac})"
        )

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"rough '{name}': base top z={base_top_z:.3f} <= BASELINE_Z={BASELINE_Z:.3f}; "
            f"increase base_height."
        )

    if relief_mode not in ("centered", "up", "down"):
        raise ValueError(
            f"rough.relief_mode must be 'centered' | 'up' | 'down' (got {relief_mode!r})"
        )

    # 1. Generate the raw heightmap (no edge taper applied — we apply it
    #    differently per relief_mode below).
    heightmap_raw = generate_complex_terrain(
        shape=(grid_resolution, grid_resolution),
        seed=int(seed),
        terrace_levels=int(terrace_levels),
        num_pits=int(num_pits),
        num_hills=int(num_hills),
        pit_threshold=float(pit_threshold),
        plateau_threshold=float(plateau_threshold),
        edge_taper_frac=0.0,
    )
    mask = edge_taper(heightmap_raw.shape, taper_frac=float(edge_taper_frac))

    if relief_mode == "up":
        # Edges → 0 (base_top_z), features rise above.
        heightmap = heightmap_raw * mask
    elif relief_mode == "down":
        # Edges → 1 (base_top_z when origin shifted), features dip below.
        heightmap = 1.0 - (heightmap_raw * mask)
    else:  # centered
        # Edges → 0.5 (base_top_z when origin shifted by relief/2), features
        # oscillate ±vertical_relief/2 around base_top_z.
        heightmap = (heightmap_raw - 0.5) * mask + 0.5

    # 2. Save it as a grayscale PNG alongside the generated terrain XML.
    #    Filename includes the terrain_name prefix so PNGs from different
    #    configs don't collide in the shared library directory.
    output_dir.mkdir(parents=True, exist_ok=True)
    png_filename = f"{terrain_name}_{name}.png" if terrain_name else f"{name}.png"
    png_path = output_dir / png_filename
    heightmap_uint8 = np.clip((heightmap * 255).round(), 0, 255).astype(np.uint8)
    Image.fromarray(heightmap_uint8, mode="L").save(png_path)

    # 3. Declare the hfield asset. The geom origin / hfield base extent
    # depends on the relief direction:
    #   invert_relief=False: geom origin at base_top_z, surface ranges
    #     [base_top_z .. base_top_z + vertical_relief].
    #   invert_relief=True:  geom origin at base_top_z - vertical_relief,
    #     surface ranges [base_top_z - vertical_relief .. base_top_z].
    # In both cases base_z extends the hfield down to BASELINE_Z.
    #
    # Path note: MjSpec reads the PNG at spec.to_xml() time to validate
    # dimensions, so the path must be resolvable at compose time. We pass
    # the absolute path here; the composer post-processes the emitted XML
    # to rewrite it as `../terrain/<file>.png` (which is what model XMLs
    # need at load time given the nested-include resolution rules).
    if relief_mode == "up":
        geom_origin_z = base_top_z
    elif relief_mode == "down":
        geom_origin_z = base_top_z - vertical_relief
    else:  # centered
        geom_origin_z = base_top_z - vertical_relief / 2.0
    base_z_extent = geom_origin_z - BASELINE_Z
    if base_z_extent <= 0:
        raise ValueError(
            f"rough '{name}': hfield base extent {base_z_extent:.3f} is non-positive. "
            f"With relief_mode={relief_mode!r}, ensure the lowest hfield surface point "
            f"stays above BASELINE_Z={BASELINE_Z}."
        )
    hfield_name = f"{name}_hfield"
    spec.add_hfield(
        name=hfield_name,
        nrow=grid_resolution,
        ncol=grid_resolution,
        size=[tile_size[0] / 2, tile_size[1] / 2, vertical_relief, base_z_extent],
        file=str(png_path.resolve()).replace("\\", "/"),
    )

    # 4. Emit the hfield geom on worldbody (static, no body wrapper).
    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_HFIELD,
        "hfieldname": hfield_name,
        "pos": [origin_xyz[0], origin_xyz[1], geom_origin_z],
        "contype": 1,
        "conaffinity": 1,
    }
    if material is not None:
        geom_kwargs["material"] = material
    if rgba is not None:
        geom_kwargs["rgba"] = list(rgba)

    spec.worldbody.add_geom(name=f"{name}_geom", **geom_kwargs)

    return TileEmitResult(base_height=base_height)
