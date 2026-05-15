"""Fractal-composite terrain heightmap generator.

Used by the `rough` tile to synthesize a heightmap that blends large-scale
shape (basins, plazas, hills) with high-frequency detail. Includes an
optional smooth edge taper (`edge_taper_frac`) that drives the heightmap
to 0 at the array boundary so a per-tile rough patch joins cleanly to
flat-base neighbours.

All pit/hill amplitudes are clipped (rather than divided by the global max)
so feature heights stay readable when many features overlap.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy.ndimage import gaussian_filter, zoom


def normalize(values: np.ndarray) -> np.ndarray:
    """Scale an array to [0, 1] (or zeros if it is flat)."""
    v_min = float(values.min())
    v_range = float(values.max() - v_min)
    if v_range < 1e-9:
        return np.zeros_like(values)
    return (values - v_min) / v_range


def fractal_noise(
    shape: Tuple[int, int],
    base_res: float,
    octaves: int,
    persistence: float,
    lacunarity: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate normalized fractal noise with configurable frequency bands."""
    accum = np.zeros(shape, dtype=np.float64)
    amplitude = 1.0
    amplitude_sum = 0.0
    frequency = 1.0
    aspect = shape[1] / shape[0]

    for _ in range(octaves):
        rows = max(2, int(np.ceil(base_res * frequency)))
        cols = max(2, int(np.ceil(base_res * frequency * aspect)))
        coarse = rng.random((rows, cols))
        zoom_factors = (shape[0] / rows, shape[1] / cols)
        band = zoom(coarse, zoom_factors, mode="reflect", order=3)
        band = band[: shape[0], : shape[1]]
        accum += band * amplitude
        amplitude_sum += amplitude
        amplitude *= persistence
        frequency *= lacunarity

    if amplitude_sum == 0.0:
        return np.zeros(shape, dtype=np.float64)
    return accum / amplitude_sum


def edge_taper(shape: Tuple[int, int], taper_frac: float) -> np.ndarray:
    """Smoothstep falloff to 0 at the array boundary.

    `taper_frac` is the fractional band width (of the shorter axis) over
    which the mask transitions 0 -> 1. taper_frac=0 returns an all-ones
    mask (no tapering).
    """
    if taper_frac <= 0.0:
        return np.ones(shape, dtype=np.float32)
    h, w = shape
    yy = np.linspace(0, 1, h)
    xx = np.linspace(0, 1, w)
    yy, xx = np.meshgrid(yy, xx, indexing="ij")
    d = np.minimum(np.minimum(yy, 1 - yy), np.minimum(xx, 1 - xx))
    t = np.clip(d / taper_frac, 0, 1)
    smoothed = (t * t * (3 - 2 * t)).astype(np.float32)
    return smoothed


def generate_complex_terrain(
    shape: Tuple[int, int] = (256, 256),
    seed: int = 0,
    terrace_levels: int = 5,
    num_pits: int = 12,
    num_hills: int = 16,
    pit_threshold: float = 0.33,
    plateau_threshold: float = 0.68,
    edge_taper_frac: float = 0.05,
) -> np.ndarray:
    """Synthesize mixed terrain with basins, plazas, hills, and rough patches.

    Returns a float32 array in [0, 1]. With edge_taper_frac > 0, the array
    is 0 along its boundary and rises into the body of the heightmap; this
    keeps the rough tile flush with flat-base neighbours at the cell edge.
    """
    rng = np.random.default_rng(seed)
    yy = np.linspace(-1.0, 1.0, shape[0])
    xx = np.linspace(-1.0, 1.0, shape[1])
    yy, xx = np.meshgrid(yy, xx, indexing="ij")

    pit_cut = float(np.clip(pit_threshold, 0.05, 0.5))
    plateau_cut = float(np.clip(plateau_threshold, pit_cut + 0.05, 0.9))

    macro = fractal_noise(shape, base_res=5.5, octaves=4, persistence=0.55, lacunarity=2.1, rng=rng)
    macro = gaussian_filter(macro, sigma=5.5)
    macro = normalize(macro)

    selector = fractal_noise(shape, base_res=2.5, octaves=3, persistence=0.55, lacunarity=2.0, rng=rng)
    selector = normalize(selector)

    pit_weight = gaussian_filter((selector < pit_cut).astype(np.float32), sigma=5.0)
    plateau_weight = gaussian_filter(
        ((selector >= pit_cut) & (selector < plateau_cut)).astype(np.float32), sigma=5.0
    )
    rough_weight = gaussian_filter((selector >= plateau_cut).astype(np.float32), sigma=5.0)
    weight_sum = pit_weight + plateau_weight + rough_weight + 1e-8
    pit_weight /= weight_sum
    plateau_weight /= weight_sum
    rough_weight /= weight_sum

    pits = np.zeros(shape, dtype=np.float32)
    for _ in range(max(num_pits, 0)):
        center = rng.uniform(-0.9, 0.9, size=2)
        radius = rng.uniform(0.04, 0.10)
        depth = rng.uniform(0.4, 0.85)
        dist = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2)
        pits -= depth * np.exp(-(dist**2) / (2.0 * radius**2))
    pit_contrib = np.clip(pits, -1.0, 0.0)

    hills = np.zeros(shape, dtype=np.float32)
    for _ in range(max(num_hills, 0)):
        center = rng.uniform(-0.9, 0.9, size=2)
        radius = rng.uniform(0.04, 0.10)
        height = rng.uniform(0.35, 0.8)
        dist = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2)
        hills += height * np.exp(-(dist**2) / (2.0 * radius**2))
    hill_contrib = np.clip(hills, 0.0, 1.0)

    plateau_source = gaussian_filter(macro, sigma=6.5)
    plateau_steps = np.round(normalize(plateau_source) * terrace_levels) / max(terrace_levels, 1)
    plateau_contrib = plateau_steps - 0.5

    detail_noise = fractal_noise(shape, base_res=80.0, octaves=4, persistence=0.6, lacunarity=2.6, rng=rng)
    detail_noise = normalize(detail_noise)
    detail_variation = detail_noise - gaussian_filter(detail_noise, sigma=1.4)
    detail_variation = np.clip(detail_variation, -0.6, 0.6)

    terrain = (
        0.30 * macro
        + 1.00 * pit_weight * pit_contrib
        + 0.55 * plateau_weight * plateau_contrib
        + 0.90 * rough_weight * (hill_contrib + 0.35 * detail_variation)
        + 0.18 * detail_variation
    )
    terrain = normalize(terrain)
    terrain = np.clip(0.85 * terrain + 0.15 * gaussian_filter(terrain, sigma=1.0), 0.0, 1.0)

    if edge_taper_frac > 0.0:
        terrain = terrain * edge_taper(shape, taper_frac=edge_taper_frac)

    return terrain.astype(np.float32)
