"""`rough` tile: hfield-based naturalistic terrain.

Generates a per-tile heightmap PNG via the fractal-composite noise
generator (see `myoassist_terrains.noise`), declares an `<asset><hfield/>` for it,
and emits a single hfield geom that occupies the tile.

The heightmap is edge-tapered so the surface lands on `base_height` around the
whole perimeter, satisfying the flat-at-base contract. The taper drives the
*heightmap* to whichever value means "base" for the chosen `relief_mode` -- 0 for
`up`, 1 for `down`, 0.5 for `centered` -- not to 0 in every case.

MuJoCo renormalizes hfield data to its own [min, max] before scaling by
`size[2]`, so a heightmap that does not happen to span the full [0, 1] range gets
stretched. `_hfield_placement` below inverts that renormalization when choosing
the geom origin, which is what keeps the perimeter on `base_height` in every
mode (`centered` was 3.6% of `vertical_relief` high before this was accounted
for). `vertical_relief` therefore means the true peak-to-trough excursion.

Hfield geometry mapping (MuJoCo `size` = `(half_x, half_y, max_z, base_z)`):
- half_x, half_y: full tile half-extents
- max_z:  `vertical_relief`, the physical excursion the data range maps onto
- base_z: solid thickness below the geom origin, down to BASELINE_Z

PNG file names carry a short digest of the heightmap bytes. MuJoCo caches decoded
file assets by path within a process, so a name derived only from the terrain and
tile would silently serve a stale heightfield when a config is rebuilt in-process
under the same name. The emitted path uses a `../terrain/<file>.png` prefix
because MuJoCo resolves nested-include asset paths relative to the top-level
model file's directory (one level above `model/terrain/`).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
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

PARAM_DOCS: dict[str, str] = {
    "seed": "RNG seed for the heightmap.",
    "vertical_relief": "Peak-to-trough excursion of the surface in meters.",
    "grid_resolution": "Heightmap resolution in pixels per side.",
    "num_pits": "Number of gaussian pit features blended in.",
    "num_hills": "Number of gaussian hill features blended in.",
    "terrace_levels": "Plateau quantization levels.",
    "pit_threshold": "Selector cutoff below which a macro region becomes a pit.",
    "plateau_threshold": "Selector cutoff above which a macro region becomes rough.",
    "edge_taper_frac": "Fractional band over which the surface returns to base_height at the tile edge.",
    "relief_mode": "Whether features go both ways around base_height ('centered'), only up, or only down.",
    "base_height": "z-coordinate of the tile's flat-edge base.",
}

SPEED_SCALE = 0.42

RELIEF_MODES = ("centered", "up", "down")


@lru_cache(maxsize=64)
def _quantized_heightmap(
    seed: int,
    grid_resolution: int,
    terrace_levels: int,
    num_pits: int,
    num_hills: int,
    pit_threshold: float,
    plateau_threshold: float,
    edge_taper_frac: float,
    relief_mode: str,
) -> np.ndarray:
    """The heightmap exactly as the PNG stores it, as uint8.

    Quantizing here rather than at write time means `emit` and `surface_height`
    reason about the same bytes MuJoCo will decode, so the two cannot disagree by
    a rounding step. Cached because a velocity map samples one tile thousands of
    times and the generator is the expensive part.
    """
    raw = generate_complex_terrain(
        shape=(grid_resolution, grid_resolution),
        seed=seed,
        terrace_levels=terrace_levels,
        num_pits=num_pits,
        num_hills=num_hills,
        pit_threshold=pit_threshold,
        plateau_threshold=plateau_threshold,
        edge_taper_frac=0.0,
    )
    mask = edge_taper(raw.shape, taper_frac=edge_taper_frac)
    if relief_mode == "up":
        heightmap = raw * mask  # edges -> 0
    elif relief_mode == "down":
        heightmap = 1.0 - (raw * mask)  # edges -> 1
    else:  # centered; edges -> 0.5
        heightmap = (raw - 0.5) * mask + 0.5
    return np.clip((heightmap * 255).round(), 0, 255).astype(np.uint8)


def _heightmap_from_params(params: dict) -> np.ndarray:
    return _quantized_heightmap(
        int(params.get("seed", 0)),
        int(params.get("grid_resolution", 256)),
        int(params.get("terrace_levels", 5)),
        int(params.get("num_pits", 18)),
        int(params.get("num_hills", 24)),
        float(params.get("pit_threshold", 0.33)),
        float(params.get("plateau_threshold", 0.68)),
        float(params.get("edge_taper_frac", 0.10)),
        str(params.get("relief_mode", "centered")),
    )


def _hfield_placement(quantized: np.ndarray, base_top_z: float, vertical_relief: float):
    """Return (geom_origin_z, hmin, span) that put the tapered edge on base_top_z.

    MuJoCo computes `surface = origin + size[2] * (h - hmin) / (hmax - hmin)`, so
    to land the edge value on `base_top_z` the origin has to absorb that
    renormalization:

        origin = base_top_z - relief * (h_edge - hmin) / span

    `up` and `down` come out unchanged because their edge value is already a data
    extreme; `centered` is the mode this corrects.
    """
    normalized = quantized.astype(np.float64) / 255.0
    hmin = float(normalized.min())
    hmax = float(normalized.max())
    span = max(hmax - hmin, 1e-9)
    h_edge = float(normalized[0, 0])  # the taper drives the whole boundary to one value
    geom_origin_z = base_top_z - vertical_relief * (h_edge - hmin) / span
    return geom_origin_z, hmin, span


def surface_height(
    local_x: float,
    local_y: float,
    *,
    tile_size: tuple[float, float],
    vertical_relief: float = 0.8,
    base_height: float = 0.0,
    **params,
) -> float:
    """Walkable surface height at a tile-local (x, y).

    Samples the same quantized heightmap `emit` writes and applies the same
    placement, so this reports what MuJoCo will actually build.

    Note the y inversion. `Image.fromarray` writes array row 0 as the top image
    row, and MuJoCo loads image row 0 into the hfield's LAST row, whose rows run
    along +y. So world `local_y = -half` corresponds to array row `nrow - 1`, not
    row 0 -- sampling it the other way round mirrors the whole tile.
    """
    quantized = _heightmap_from_params(
        {"vertical_relief": vertical_relief, "base_height": base_height, **params}
    )
    origin, hmin, span = _hfield_placement(quantized, float(base_height), float(vertical_relief))
    value = _bilinear_sample(quantized, local_x, local_y, tile_size)
    return float(origin + vertical_relief * (value - hmin) / span)


def _bilinear_sample(quantized: np.ndarray, local_x: float, local_y: float, tile_size) -> float:
    """Bilinear sample of the normalized heightmap at a tile-local coordinate."""
    nrow, ncol = quantized.shape
    u = (local_x / tile_size[0]) + 0.5
    v = 0.5 - (local_y / tile_size[1])  # see surface_height's note on the y inversion
    px = max(0.0, min(ncol - 1.0, u * (ncol - 1)))
    py = max(0.0, min(nrow - 1.0, v * (nrow - 1)))

    x0, y0 = int(np.floor(px)), int(np.floor(py))
    x1, y1 = min(x0 + 1, ncol - 1), min(y0 + 1, nrow - 1)
    tx, ty = px - x0, py - y0

    grid = quantized.astype(np.float64) / 255.0
    top = grid[y0, x0] * (1.0 - tx) + grid[y0, x1] * tx
    bottom = grid[y1, x0] * (1.0 - tx) + grid[y1, x1] * tx
    return float(top * (1.0 - ty) + bottom * ty)


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
            f"rough tile {name!r} requires `output_dir` to write its hfield PNG; the composer should pass this automatically."
        )
    if vertical_relief <= 0:
        raise ValueError(f"rough.vertical_relief must be > 0 (got {vertical_relief})")
    if grid_resolution < 8:
        raise ValueError(f"rough.grid_resolution must be >= 8 (got {grid_resolution})")
    if not (0.0 <= edge_taper_frac < 0.5):
        raise ValueError(f"rough.edge_taper_frac must satisfy 0 <= frac < 0.5 (got {edge_taper_frac})")
    if relief_mode not in RELIEF_MODES:
        raise ValueError(f"rough.relief_mode must be one of {RELIEF_MODES} (got {relief_mode!r})")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(f"rough '{name}': base top z={base_top_z:.3f} <= BASELINE_Z={BASELINE_Z:.3f}; increase base_height.")

    # 1. Generate the heightmap, quantized exactly as the PNG will hold it.
    quantized = _quantized_heightmap(
        int(seed),
        int(grid_resolution),
        int(terrace_levels),
        int(num_pits),
        int(num_hills),
        float(pit_threshold),
        float(plateau_threshold),
        float(edge_taper_frac),
        relief_mode,
    )

    # 2. Write it beside the generated terrain XML. The digest makes the name
    #    content-addressed: identical data reuses one file, different data never
    #    collides, and MuJoCo's per-process path cache can never serve stale
    #    elevation for a rebuilt config.
    digest = hashlib.blake2b(quantized.tobytes(), digest_size=4).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{terrain_name}_{name}" if terrain_name else name
    png_path = output_dir / f"{stem}_{digest}.png"
    if not png_path.exists():
        Image.fromarray(quantized, mode="L").save(png_path)

    # 3. Declare the hfield asset, inverting MuJoCo's renormalization so the
    #    tapered edge lands on base_top_z. See `_hfield_placement`.
    #
    #    Path note: MjSpec reads the PNG at spec.to_xml() time to validate
    #    dimensions, so the path must be resolvable at compose time. We pass
    #    the absolute path here; the composer post-processes the emitted XML
    #    to rewrite it as `../terrain/<file>.png` (which is what model XMLs
    #    need at load time given the nested-include resolution rules).
    geom_origin_z, _hmin, _span = _hfield_placement(quantized, base_top_z, vertical_relief)
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
