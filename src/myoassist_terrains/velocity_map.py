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

from myoassist_terrains.config import TerrainConfig, TileConfig
from myoassist_terrains.composer import compute_cell_layouts, resolve_tiles
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
    assert samples_per_tile >= 1
    assert base_speed > 0.0
    assert height_offset >= 0.0
    assert mode in {"goal", "tile"}
    assert tile_radial_mode in {"inward", "outward", "mixed"}
    assert 0.0 <= tile_speed_jitter < 1.0

    start_v = np.asarray(start, dtype=float)
    goal_v = np.asarray(goal, dtype=float)
    assert start_v.shape == (3,)
    assert goal_v.shape == (3,)
    assert np.linalg.norm(goal_v[:2] - start_v[:2]) > 1e-9

    scales = dict(DEFAULT_SPEED_SCALE)
    if speed_scale is not None:
        scales.update(speed_scale)

    layouts = compute_cell_layouts(config)
    tiles = resolve_tiles(config)
    tw, tl = config.grid.tile_size

    offsets_x = _sample_offsets(tw, samples_per_tile)
    offsets_y = _sample_offsets(tl, samples_per_tile)
    out: list[VelocitySample] = []

    for tile in tiles:
        assert tile.type in REGISTRY
        scale = scales.get(tile.type)
        assert scale is not None, f"missing speed scale for tile type {tile.type!r}"
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
                direction, grade = _direction_and_grade(config, tiles, x, y, z, direction_xy)
                roughness = _local_surface_roughness(config, tiles, x, y, z)
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
    margin = 0.18 * length / max(count, 1)
    return np.linspace(-length / 2 + margin, length / 2 - margin, count)


def _goal_direction_xy(x: float, y: float, goal: np.ndarray) -> np.ndarray:
    horizontal = goal[:2] - np.asarray([x, y], dtype=float)
    norm = float(np.linalg.norm(horizontal))
    if norm < 1e-9:
        return np.asarray([0.0, 0.0], dtype=float)
    return horizontal / norm


def _direction_and_grade(
    config: TerrainConfig,
    tiles: Iterable[TileConfig],
    x: float,
    y: float,
    z: float,
    direction_xy: np.ndarray,
) -> tuple[np.ndarray, float]:
    assert direction_xy.shape == (2,)
    norm_xy = float(np.linalg.norm(direction_xy))
    if norm_xy < 1e-9:
        return np.asarray([0.0, 0.0, 0.0]), 0.0

    step_xy = direction_xy / norm_xy
    probe_distance = 0.5
    probe_xy = np.asarray([x, y], dtype=float) + step_xy * probe_distance
    probe_z = surface_height_at(config, tiles, float(probe_xy[0]), float(probe_xy[1]))
    direction = np.asarray([step_xy[0], step_xy[1], probe_z - z], dtype=float)
    norm = float(np.linalg.norm(direction))
    assert norm > 1e-12
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

    if tile.type == "pyramid_stairs":
        direction = _radial_direction(tile, local_x, local_y, radial_mode)
        norm = float(np.linalg.norm(direction))
        if norm > 1e-9:
            return direction / norm

    if tile.type in {"rough", "discrete_obstacles", "stepping_stones", "boulders"}:
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
    assert radial_mode in {"inward", "outward", "mixed"}
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
    assert grade >= 0.0
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


def _local_surface_roughness(
    config: TerrainConfig,
    tiles: Iterable[TileConfig],
    x: float,
    y: float,
    z: float,
) -> float:
    """Estimate local surface unevenness independent of goal direction."""
    probe = 0.35
    heights = [
        surface_height_at(config, tiles, x + probe, y),
        surface_height_at(config, tiles, x - probe, y),
        surface_height_at(config, tiles, x, y + probe),
        surface_height_at(config, tiles, x, y - probe),
    ]
    return max(abs(float(h - z)) / probe for h in heights)


def surface_height_at(
    config: TerrainConfig,
    tiles: Iterable[TileConfig],
    x: float,
    y: float,
) -> float:
    layouts = compute_cell_layouts(config)
    tw, tl = config.grid.tile_size
    for tile in tiles:
        layout = layouts[(tile.row, tile.col)]
        local_x = x - layout.center_x
        local_y = y - layout.center_y
        if abs(local_x) <= tw / 2 and abs(local_y) <= tl / 2:
            return estimate_surface_height(tile, local_x, local_y, config.grid.tile_size)
    return 0.0
