from __future__ import annotations

import numpy as np

from myoassist_terrains.config import BorderConfig, GridConfig, TerrainConfig, TileConfig
from myoassist_terrains.velocity_map import generate_velocity_map


def test_velocity_map_samples_every_tile_point():
    cfg = TerrainConfig(
        terrain_name="vm",
        grid=GridConfig(rows=1, cols=2, tile_size=(2.0, 2.0)),
        border=BorderConfig(width=0.0),
        tiles=[
            TileConfig(row=0, col=0, type="flat"),
            TileConfig(row=0, col=1, type="rough"),
        ],
    )

    samples = generate_velocity_map(
        cfg,
        start=(-2.0, 0.0, 0.0),
        goal=(2.0, 0.0, 0.0),
        samples_per_tile=2,
        base_speed=1.0,
    )

    assert len(samples) == 8
    # Compare the slowest flat sample against the fastest rough one, rather than
    # collapsing into a dict where the last sample of each type wins.
    flat = [s.speed for s in samples if s.tile_type == "flat"]
    rough = [s.speed for s in samples if s.tile_type == "rough"]
    assert len(flat) == len(rough) == 4
    assert min(flat) > max(rough)


def test_velocity_map_vectors_point_toward_goal():
    cfg = TerrainConfig(
        terrain_name="vm",
        grid=GridConfig(rows=1, cols=1, tile_size=(2.0, 2.0)),
        border=BorderConfig(width=0.0),
        tiles=[TileConfig(row=0, col=0, type="flat")],
    )

    sample = generate_velocity_map(
        cfg,
        start=(-1.0, 0.0, 0.0),
        goal=(3.0, 0.0, 0.0),
        samples_per_tile=1,
    )[0]

    velocity = np.asarray(sample.velocity)
    to_goal = np.asarray([3.0, 0.0, 0.0]) - np.asarray(sample.position)
    assert float(np.dot(velocity, to_goal)) > 0.0


def test_tile_mode_uses_stair_axis_direction():
    cfg = TerrainConfig(
        terrain_name="vm",
        grid=GridConfig(rows=1, cols=1, tile_size=(4.0, 4.0)),
        border=BorderConfig(width=0.0),
        tiles=[TileConfig(row=0, col=0, type="stairs", params={"axis": "y"})],
    )

    sample = generate_velocity_map(
        cfg,
        start=(0.0, -2.0, 0.0),
        goal=(-10.0, 0.0, 0.0),
        samples_per_tile=1,
        mode="tile",
    )[0]

    velocity = np.asarray(sample.velocity)
    assert velocity[1] > 0.0
    assert abs(velocity[0]) < 1e-9


def test_tile_mode_can_use_radial_outward_direction():
    cfg = TerrainConfig(
        terrain_name="vm",
        grid=GridConfig(rows=1, cols=1, tile_size=(4.0, 4.0)),
        border=BorderConfig(width=0.0),
        tiles=[TileConfig(row=0, col=0, type="pyramid_stairs")],
    )

    samples = generate_velocity_map(
        cfg,
        start=(0.0, 0.0, 0.0),
        goal=(-10.0, 0.0, 0.0),
        samples_per_tile=3,
        mode="tile",
        tile_radial_mode="outward",
    )

    sample = max(samples, key=lambda s: s.position[0])
    velocity = np.asarray(sample.velocity)
    assert velocity[0] > 0.0
