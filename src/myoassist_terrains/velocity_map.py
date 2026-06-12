"""Velocity field generation over terrain configs.

The map is sampled in world coordinates over terrain tiles. Each sample
points toward the goal and scales speed by the local tile type, with a
lightweight surface-height estimate used for 3D placement and slope-aware
vertical direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import numpy as np

from myoassist_terrains.config import TerrainConfig, TileConfig
from myoassist_terrains.composer import _compute_cell_layouts, _resolve_tiles
from myoassist_terrains.noise import edge_taper, generate_complex_terrain
from myoassist_terrains.tiles import REGISTRY


DEFAULT_SPEED_SCALE: dict[str, float] = {
    "flat": 1.00,
    "slope": 0.72,
    "stairs": 0.55,
    "pyramid_stairs": 0.50,
    "rough": 0.42,
    "discrete_obstacles": 0.38,
    "stepping_stones": 0.35,
    "boulders": 0.32,
    "gap": 0.25,
}


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
) -> list[VelocitySample]:
    """Generate a sampled 3D velocity map over a terrain config."""
    assert samples_per_tile >= 1
    assert base_speed > 0.0
    assert height_offset >= 0.0
    assert mode in {"goal", "tile"}
    assert tile_radial_mode in {"inward", "outward", "mixed"}

    start_v = np.asarray(start, dtype=float)
    goal_v = np.asarray(goal, dtype=float)
    assert start_v.shape == (3,)
    assert goal_v.shape == (3,)
    assert np.linalg.norm(goal_v[:2] - start_v[:2]) > 1e-9

    scales = dict(DEFAULT_SPEED_SCALE)
    if speed_scale is not None:
        scales.update(speed_scale)

    layouts = _compute_cell_layouts(config)
    tiles = _resolve_tiles(config)
    tw, tl = config.grid.tile_size

    offsets_x = _sample_offsets(tw, samples_per_tile)
    offsets_y = _sample_offsets(tl, samples_per_tile)
    out: list[VelocitySample] = []

    for tile in tiles:
        assert tile.type in REGISTRY
        scale = scales.get(tile.type)
        assert scale is not None, f"missing speed scale for tile type {tile.type!r}"
        layout = layouts[(tile.row, tile.col)]

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
                speed = base_speed * scale * _grade_speed_scale(max(grade, roughness))
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
    """Approximate walkable surface height at a local tile coordinate."""
    params = dict(REGISTRY[tile.type].default_params)
    params.update(tile.params)

    if tile.type == "flat":
        return float(params.get("height", 0.0))
    if tile.type == "slope":
        return _slope_height(params, local_x, local_y, tile_size)
    if tile.type == "stairs":
        return _stairs_height(params, local_x, local_y, tile_size)
    if tile.type == "pyramid_stairs":
        return _pyramid_height(params, local_x, local_y, tile_size)
    if tile.type == "rough":
        return _rough_height(params, local_x, local_y, tile_size)
    return float(params.get("base_height", 0.0))


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
    layouts = _compute_cell_layouts(config)
    tw, tl = config.grid.tile_size
    for tile in tiles:
        layout = layouts[(tile.row, tile.col)]
        local_x = x - layout.center_x
        local_y = y - layout.center_y
        if abs(local_x) <= tw / 2 and abs(local_y) <= tl / 2:
            return estimate_surface_height(tile, local_x, local_y, config.grid.tile_size)
    return 0.0


def _axis_value(axis: str, local_x: float, local_y: float) -> float:
    assert axis in {"x", "y"}
    return local_x if axis == "x" else local_y


def _slope_height(params: dict, local_x: float, local_y: float, tile_size: tuple[float, float]) -> float:
    axis = str(params.get("axis", "y"))
    base = float(params.get("base_height", 0.0))
    long_total = tile_size[1] if axis == "y" else tile_size[0]
    local = _axis_value(axis, local_x, local_y)
    plateau_ratio = float(params.get("plateau_ratio", 0.1))
    ramp_len = (long_total - plateau_ratio * long_total) / 2.0
    excursion = ramp_len * math.tan(math.radians(float(params.get("angle_deg", 12.0))))
    if bool(params.get("inverted", False)):
        excursion *= -1.0

    dist_from_edge = min(local + long_total / 2.0, long_total / 2.0 - local)
    t = max(0.0, min(1.0, dist_from_edge / ramp_len))
    return base + excursion * t


def _stairs_height(params: dict, local_x: float, local_y: float, tile_size: tuple[float, float]) -> float:
    axis = str(params.get("axis", "y"))
    base = float(params.get("base_height", 0.0))
    long_total = tile_size[1] if axis == "y" else tile_size[0]
    local = _axis_value(axis, local_x, local_y)
    n_steps = int(params.get("n_steps", 6))
    step_height = float(params.get("step_height", 0.15))
    peak_width = float(params.get("peak_width", 0.4))
    step_width = params.get("step_width")
    if step_width is None:
        step_width = (long_total - peak_width) / (2 * n_steps)
    step_width = float(step_width)
    dist_from_edge = min(local + long_total / 2.0, long_total / 2.0 - local)
    level = min(n_steps, max(0, int(dist_from_edge / step_width)))
    excursion = level * step_height
    if bool(params.get("inverted", False)):
        excursion *= -1.0
    return base + excursion


def _pyramid_height(params: dict, local_x: float, local_y: float, tile_size: tuple[float, float]) -> float:
    base = float(params.get("base_height", 0.0))
    n_steps = int(params.get("n_steps", 5))
    step_height = float(params.get("step_height", 0.2))
    step_width = float(params.get("step_width", 0.5))
    outer_margin = float(params.get("outer_margin", 0.5))
    edge_dist = min(
        tile_size[0] / 2.0 - abs(local_x),
        tile_size[1] / 2.0 - abs(local_y),
    )
    level = min(n_steps, max(0, int((edge_dist - outer_margin) / step_width) + 1))
    excursion = level * step_height
    if bool(params.get("inverted", False)):
        excursion *= -1.0
    return base + excursion


def _rough_height(params: dict, local_x: float, local_y: float, tile_size: tuple[float, float]) -> float:
    base = float(params.get("base_height", 0.0))
    relief = float(params.get("vertical_relief", 0.8))
    relief_mode = str(params.get("relief_mode", "centered"))
    assert relief_mode in {"centered", "up", "down"}

    heightmap = _rough_heightmap(
        int(params.get("seed", 0)),
        int(params.get("grid_resolution", 256)),
        int(params.get("terrace_levels", 5)),
        int(params.get("num_pits", 18)),
        int(params.get("num_hills", 24)),
        float(params.get("pit_threshold", 0.33)),
        float(params.get("plateau_threshold", 0.68)),
        float(params.get("edge_taper_frac", 0.10)),
        relief_mode,
    )
    value = _bilinear_heightmap_sample(heightmap, local_x, local_y, tile_size)
    if relief_mode == "up":
        return base + value * relief
    if relief_mode == "down":
        return base - relief + value * relief
    return base - relief / 2.0 + value * relief


@lru_cache(maxsize=64)
def _rough_heightmap(
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
        return raw * mask
    if relief_mode == "down":
        return 1.0 - (raw * mask)
    return (raw - 0.5) * mask + 0.5


def _bilinear_heightmap_sample(
    heightmap: np.ndarray,
    local_x: float,
    local_y: float,
    tile_size: tuple[float, float],
) -> float:
    h, w = heightmap.shape
    u = (local_x / tile_size[0]) + 0.5
    v = (local_y / tile_size[1]) + 0.5
    px = max(0.0, min(w - 1.0, u * (w - 1)))
    py = max(0.0, min(h - 1.0, v * (h - 1)))

    x0 = int(math.floor(px))
    y0 = int(math.floor(py))
    x1 = min(x0 + 1, w - 1)
    y1 = min(y0 + 1, h - 1)
    tx = px - x0
    ty = py - y0

    a = float(heightmap[y0, x0]) * (1.0 - tx) + float(heightmap[y0, x1]) * tx
    b = float(heightmap[y1, x0]) * (1.0 - tx) + float(heightmap[y1, x1]) * tx
    return a * (1.0 - ty) + b * ty
