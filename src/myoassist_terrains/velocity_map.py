"""Velocity field generation over terrain configs.

The map is sampled in world coordinates over terrain tiles. Each sample
points toward the goal and scales speed by the local tile type, with a
lightweight surface-height estimate used for 3D placement and slope-aware
vertical direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from myoassist_terrains.composer import compute_cell_layouts, resolve_tiles
from myoassist_terrains.config import TerrainConfig, TileConfig, UniformTerrainConfig
from myoassist_terrains.surface import TerrainSurface
from myoassist_terrains.tiles import REGISTRY

# Per-tile-type speed multipliers, derived from the registry rather than restated
# here: each tile declares its own SPEED_SCALE, so a tile registered through
# `register_tile` is covered automatically and this table cannot fall out of step
# with the tile set. Read it for reporting; pass `speed_scale=` to override.
DEFAULT_SPEED_SCALE: dict[str, float] = {name: impl.default_speed_scale for name, impl in REGISTRY.items()}


@dataclass(frozen=True)
class VelocitySample:
    row: int
    col: int
    tile_type: str
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    speed: float


def generate_velocity_map(
    config: TerrainConfig,
    *,
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    samples_per_tile: int = 10,
    base_speed: float = 1.0,
    height_offset: float = 0.35,
    speed_scale: dict[str, float] | None = None,
    mode: str = "goal",
    smooth_speeds: bool = True,
    tile_radial_mode: str = "mixed",
    tile_speed_jitter: float = 0.0,
    tile_jitter_seed: int = 0,
) -> list[VelocitySample]:
    """Generate a sampled 3D velocity map over a terrain config.

    `tile_speed_jitter` (0..1) applies a deterministic per-tile speed multiplier
    in [1 - jitter, 1 + jitter], keyed by (row, col) and `tile_jitter_seed`, so
    even identical-type tiles get distinct speeds/colours. 0 disables it.
    """
    # Raised, not asserted: `python -O` strips asserts, and these validate
    # caller input, including the spelling of `mode` and `tile_radial_mode`.
    if isinstance(config, UniformTerrainConfig):
        raise ValueError(
            "generate_velocity_map needs the grid/tile config form; a uniform terrain has no "
            "cells to sample over. Use myoassist_terrains.surface_height_at for point queries "
            "on a uniform surface."
        )
    if samples_per_tile < 1:
        raise ValueError(f"samples_per_tile must be >= 1, got {samples_per_tile}")
    if base_speed <= 0.0:
        raise ValueError(f"base_speed must be > 0, got {base_speed}")
    if height_offset < 0.0:
        raise ValueError(f"height_offset must be >= 0, got {height_offset}")
    if mode not in {"goal", "tile"}:
        raise ValueError(f"mode must be 'goal' or 'tile', got {mode!r}")
    if tile_radial_mode not in {"inward", "outward", "mixed"}:
        raise ValueError(f"tile_radial_mode must be 'inward', 'outward' or 'mixed', got {tile_radial_mode!r}")
    if not (0.0 <= tile_speed_jitter < 1.0):
        raise ValueError(f"tile_speed_jitter must be in [0, 1), got {tile_speed_jitter}")

    start_v = np.asarray(start, dtype=float)
    goal_v = np.asarray(goal, dtype=float)
    if start_v.shape != (3,) or goal_v.shape != (3,):
        raise ValueError(f"start and goal must be 3-vectors, got {start_v.shape} and {goal_v.shape}")
    if float(np.linalg.norm(goal_v[:2] - start_v[:2])) <= 1e-9:
        raise ValueError("start and goal must differ horizontally to define a direction")

    scales = dict(DEFAULT_SPEED_SCALE)
    if speed_scale is not None:
        scales.update(speed_scale)

    layouts = compute_cell_layouts(config)
    tiles = resolve_tiles(config)
    # One surface for the whole map: it resolves the tiles and the cell layout
    # once, instead of rebuilding them on each of the five height queries every
    # sample makes.
    surface = TerrainSurface(config)
    tw, tl = config.grid.tile_size

    offsets_x = _sample_offsets(tw, samples_per_tile)
    offsets_y = _sample_offsets(tl, samples_per_tile)
    out: list[VelocitySample] = []

    for tile in tiles:
        if tile.type not in scales:
            raise ValueError(
                f"no speed scale for tile type {tile.type!r}. A tile registered through "
                f"register_tile(..., speed_scale=...) supplies its own; otherwise pass "
                f"speed_scale={{{tile.type!r}: <multiplier>}} here."
            )
        scale = scales[tile.type]
        layout = layouts[(tile.row, tile.col)]
        jitter = _tile_speed_jitter(tile.row, tile.col, tile_speed_jitter, tile_jitter_seed)

        for oy in offsets_y:
            for ox in offsets_x:
                x = layout.center_x + ox
                y = layout.center_y + oy
                z = estimate_surface_height(tile, ox, oy, config.grid.tile_size)
                goal_direction_xy = _goal_direction_xy(x, y, goal_v)
                if mode == "tile":
                    direction_xy = _tile_direction_xy(tile, ox, oy, goal_direction_xy, tile_radial_mode)
                else:
                    direction_xy = goal_direction_xy
                direction, grade = _direction_and_grade(surface, x, y, z, direction_xy)
                roughness = _local_surface_roughness(surface, x, y, z)
                speed = base_speed * scale * _grade_speed_scale(max(grade, roughness)) * jitter
                velocity = direction * speed
                out.append(
                    VelocitySample(
                        row=tile.row,
                        col=tile.col,
                        tile_type=tile.type,
                        position=(float(x), float(y), float(z + height_offset)),
                        velocity=(float(velocity[0]), float(velocity[1]), float(velocity[2])),
                        speed=float(speed),
                    )
                )

    if smooth_speeds:
        spacing = min(tw, tl) / max(samples_per_tile, 1)
        out = _smooth_sample_speeds(out, radius=spacing * 1.75, iterations=2, blend=0.55)

    return out


def estimate_surface_height(
    tile: TileConfig,
    local_x: float,
    local_y: float,
    tile_size: tuple[float, float],
) -> float:
    """Walkable surface height at a tile-local coordinate.

    Dispatches to the tile's own `surface_height`, which lives beside the `emit`
    that placed the geometry. This module used to keep a second, hand-derived
    model of every tile; it disagreed with the emitted surface for four of the
    nine tile types, which is why the height model now belongs to the tile.

    A tile registered without a `surface_height` falls back to its `base_height`
    parameter, which is correct only for a flat-topped tile.
    """
    impl = REGISTRY[tile.type]
    params = dict(impl.default_params)
    params.update(tile.params)
    if impl.surface_height_fn is None:
        return float(params.get("height", params.get("base_height", 0.0)))
    return float(impl.surface_height_fn(local_x, local_y, tile_size=tile_size, **params))


def _tile_speed_jitter(row: int, col: int, amplitude: float, seed: int) -> float:
    """Deterministic per-tile speed multiplier in [1 - amplitude, 1 + amplitude].

    Stable across runs (no Python hash randomisation): mixes (row, col, seed)
    with large odd constants. amplitude <= 0 returns 1.0 (no variation).
    """
    if amplitude <= 0.0:
        return 1.0
    h = (int(row) * 73856093) ^ (int(col) * 19349663) ^ (int(seed) * 83492791)
    frac = (h & 0xFFFFFFFF) / float(0xFFFFFFFF)  # [0, 1]
    return 1.0 + amplitude * (2.0 * frac - 1.0)


def _sample_offsets(length: float, count: int) -> np.ndarray:
    """Sample offsets across one tile axis, inset from the edges.

    A single sample belongs at the tile centre. `np.linspace(a, b, 1)` returns
    the low endpoint, so the count==1 case used to place its one sample 32% of
    the tile away from the centre.
    """
    if count == 1:
        return np.zeros(1)
    margin = 0.18 * length / max(count, 1)
    return np.linspace(-length / 2 + margin, length / 2 - margin, count)


def _goal_direction_xy(x: float, y: float, goal: np.ndarray) -> np.ndarray:
    horizontal = goal[:2] - np.asarray([x, y], dtype=float)
    norm = float(np.linalg.norm(horizontal))
    if norm < 1e-9:
        return np.asarray([0.0, 0.0], dtype=float)
    return horizontal / norm


def _direction_and_grade(
    surface: TerrainSurface,
    x: float,
    y: float,
    z: float,
    direction_xy: np.ndarray,
) -> tuple[np.ndarray, float]:
    assert direction_xy.shape == (2,)  # internal invariant: built by this module
    norm_xy = float(np.linalg.norm(direction_xy))
    if norm_xy < 1e-9:
        return np.asarray([0.0, 0.0, 0.0]), 0.0

    step_xy = direction_xy / norm_xy
    probe_distance = 0.5
    probe_xy = np.asarray([x, y], dtype=float) + step_xy * probe_distance
    probe_z = surface.height_at(float(probe_xy[0]), float(probe_xy[1]))
    direction = np.asarray([step_xy[0], step_xy[1], probe_z - z], dtype=float)
    norm = float(np.linalg.norm(direction))
    assert norm > 1e-12  # internal invariant: step_xy is a unit vector
    grade = abs(float(probe_z - z)) / probe_distance
    return direction / norm, grade


def _tile_direction_xy(
    tile: TileConfig,
    local_x: float,
    local_y: float,
    fallback: np.ndarray,
    radial_mode: str,
) -> np.ndarray:
    params = dict(REGISTRY[tile.type].default_params)
    params.update(tile.params)

    if tile.type in {"stairs", "slope", "gap"}:
        axis = str(params.get("axis", "y"))
        assert axis in {"x", "y"}
        if axis == "x":
            return np.asarray([1.0, 0.0], dtype=float)
        return np.asarray([0.0, 1.0], dtype=float)

    # Tiles with no single travel axis get a radial flow instead.
    if tile.type in {"pyramid_stairs", "rough", "discrete_obstacles", "stepping_stones", "boulders"}:
        direction = _radial_direction(tile, local_x, local_y, radial_mode)
        norm = float(np.linalg.norm(direction))
        if norm > 1e-9:
            return direction / norm

    return fallback


def _radial_direction(
    tile: TileConfig,
    local_x: float,
    local_y: float,
    radial_mode: str,
) -> np.ndarray:
    assert radial_mode in {"inward", "outward", "mixed"}  # validated by the caller
    outward = np.asarray([local_x, local_y], dtype=float)
    if radial_mode == "outward":
        return outward
    if radial_mode == "inward":
        return -outward

    # Mixed mode gives neighbouring radial tiles different flow roles while
    # staying deterministic from the terrain config alone.
    parity = (tile.row + tile.col) % 2
    return outward if parity == 0 else -outward


def _grade_speed_scale(grade: float) -> float:
    """Slow down as surface grade increases along the travel direction."""
    assert grade >= 0.0  # internal invariant: computed as an absolute value
    return max(0.32, 1.0 / (1.0 + 2.6 * grade))


def _smooth_sample_speeds(
    samples: list[VelocitySample],
    *,
    radius: float,
    iterations: int,
    blend: float,
) -> list[VelocitySample]:
    assert radius > 0.0
    assert iterations >= 0
    assert 0.0 <= blend <= 1.0
    if not samples or iterations == 0 or blend == 0.0:
        return samples

    positions_xy = np.asarray([[s.position[0], s.position[1]] for s in samples], dtype=float)
    speeds = np.asarray([s.speed for s in samples], dtype=float)
    radius_sq = radius * radius

    for _ in range(iterations):
        next_speeds = speeds.copy()
        for i, pos in enumerate(positions_xy):
            delta = positions_xy - pos
            dist_sq = np.einsum("ij,ij->i", delta, delta)
            mask = dist_sq <= radius_sq
            weights = np.exp(-dist_sq[mask] / max(radius_sq * 0.5, 1e-9))
            local_mean = float(np.dot(weights, speeds[mask]) / weights.sum())
            next_speeds[i] = (1.0 - blend) * speeds[i] + blend * local_mean
        speeds = next_speeds

    smoothed: list[VelocitySample] = []
    for sample, speed in zip(samples, speeds):
        velocity = np.asarray(sample.velocity, dtype=float)
        norm = float(np.linalg.norm(velocity))
        if norm > 1e-12:
            velocity = velocity / norm * speed
        smoothed.append(
            VelocitySample(
                row=sample.row,
                col=sample.col,
                tile_type=sample.tile_type,
                position=sample.position,
                velocity=(float(velocity[0]), float(velocity[1]), float(velocity[2])),
                speed=float(speed),
            )
        )
    return smoothed


def _local_surface_roughness(surface: TerrainSurface, x: float, y: float, z: float) -> float:
    """Estimate local surface unevenness independent of goal direction."""
    probe = 0.35
    heights = [
        surface.height_at(x + probe, y),
        surface.height_at(x - probe, y),
        surface.height_at(x, y + probe),
        surface.height_at(x, y - probe),
    ]
    return max(abs(float(h - z)) / probe for h in heights)


def surface_height_at(
    config: TerrainConfig,
    tiles: Iterable[TileConfig] | None,  # noqa: ARG001 - kept for the published signature
    x: float,
    y: float,
) -> float:
    """Walkable surface height at world (x, y).

    Kept for the documented signature. `tiles` is accepted and ignored:
    `TerrainSurface` resolves the tiles itself, randomized ones included, so the
    caller no longer has to pre-resolve them. New code should prefer
    `myoassist_terrains.surface_height_at(config, x, y)`, which also handles the
    uniform config form and reports connector-strip heights instead of 0.0.
    """
    return TerrainSurface(config).height_at(x, y)
