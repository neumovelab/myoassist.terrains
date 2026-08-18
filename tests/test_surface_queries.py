"""The public surface-height queries, checked against ray-cast measurements.

These are what a consumer uses to place something on the terrain instead of
collision-probing a compiled model. They have to agree with the geometry that is
actually emitted, in world coordinates, over both config forms, and including the
connector strips between cells -- which the previous implementation reported as
0.0 regardless of the tiles it joined.
"""

from __future__ import annotations

import mujoco
import numpy as np
import pytest

from myoassist_terrains import build_terrain, max_surface_height_in, surface_height_at
from myoassist_terrains.config import (
    BorderConfig,
    GridConfig,
    TerrainConfig,
    TileConfig,
    config_from_dict,
)
from myoassist_terrains.surface import TerrainSurface

# mj_ray degenerates on heightfields when a probe lands exactly on a triangle
# edge: it misses and reports the hfield's base plane instead of the surface.
# There are two such families -- a probe exactly on a node line (seen at x=2.0000
# on a 64-node, 12 m field, where the fractional node index is 42.000) and a probe
# on the quad diagonal, which is any point with x == y on a square grid. So the
# two axes get DIFFERENT irregular nudges: equal nudges would still put the whole
# x == y diagonal on the degenerate edge. Without this the tolerances have to be
# loosened to roughly a full relief, which would hide real error.
_NUDGE_X = 0.00371
_NUDGE_Y = 0.00713


def _ray(model, data, x: float, y: float, start_z: float = 25.0) -> float | None:
    geomid = np.zeros(1, dtype=np.int32)
    dist = mujoco.mj_ray(
        model,
        data,
        np.array([x, y, start_z], dtype=np.float64),
        np.array([0.0, 0.0, -1.0], dtype=np.float64),
        None,
        1,
        -1,
        geomid,
    )
    return None if dist < 0 else start_z - dist


def _compiled(config, tmp_path):
    model = build_terrain(config, output_dir=tmp_path).compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, data


def _mixed_grid() -> TerrainConfig:
    """A 2x2 with a border and tiles at different heights, so connectors matter."""
    return TerrainConfig(
        terrain_name="surf_mixed",
        grid=GridConfig(rows=2, cols=2, tile_size=(6.0, 6.0)),
        border=BorderConfig(width=0.6, match_mode="min"),
        palette_preset="diverse",
        tiles=[
            TileConfig(row=0, col=0, type="flat", params={"height": 0.0}),
            TileConfig(row=0, col=1, type="flat", params={"height": 0.4}),
            TileConfig(row=1, col=0, type="flat", params={"height": 0.7}),
            TileConfig(row=1, col=1, type="stairs", params={}),
        ],
    )


def test_point_query_matches_raycast_over_a_grid(tmp_path):
    config = _mixed_grid()
    model, data = _compiled(config, tmp_path)
    surface = TerrainSurface(config)

    checked = 0
    for x in np.linspace(-6.0, 6.0, 25) + _NUDGE_X:
        for y in np.linspace(-6.0, 6.0, 25) + _NUDGE_Y:
            actual = _ray(model, data, float(x), float(y))
            if actual is None:
                continue  # off the terrain footprint
            assert surface.height_at(float(x), float(y)) == pytest.approx(actual, abs=2e-3), (
                f"height_at({x:.3f}, {y:.3f}) disagrees with the emitted surface"
            )
            checked += 1
    assert checked > 300, f"expected a dense sweep, only compared {checked} points"


def test_connector_strip_reports_the_negotiated_height(tmp_path):
    """The border strip is not 0.0: its top is match_mode over the cells it joins."""
    config = _mixed_grid()
    model, data = _compiled(config, tmp_path)
    surface = TerrainSurface(config)

    # Cell centres are at +-3.3 for a 6.0 tile with a 0.6 border, so the strip
    # between the two columns is the band around x = 0.
    on_strip = surface.height_at(0.0, -3.3)
    assert on_strip == pytest.approx(_ray(model, data, 0.0, -3.3), abs=2e-3)
    # match_mode="min" over heights 0.0 and 0.4.
    assert on_strip == pytest.approx(0.0, abs=2e-3)

    # The strip between the two rows joins 0.7 and 0.0 -> min is 0.0; between the
    # 0.4 and stairs cells it joins 0.4 and 0.0 -> 0.0. Check the corner, which
    # negotiates all four cells.
    corner = surface.height_at(0.0, 0.0)
    assert corner == pytest.approx(_ray(model, data, 0.0, 0.0), abs=2e-3)


def test_query_is_zero_beyond_the_terrain(tmp_path):
    config = _mixed_grid()
    assert surface_height_at(config, 500.0, 0.0) == 0.0
    assert surface_height_at(config, 0.0, -500.0) == 0.0


@pytest.mark.parametrize(
    "raw",
    [
        {"terrain": "flat"},
        {"terrain": "slope", "deg": 8.0},
        {"terrain": "sinusoidal", "amplitude": 0.09, "period": 1.5, "resolution": 64, "extent": 12.0},
        {"terrain": "random", "amplitude": 0.12, "resolution": 64, "extent": 12.0},
    ],
    ids=["flat", "slope", "sinusoidal", "random"],
)
def test_uniform_forms_match_raycast(raw, tmp_path):
    """Every uniform form, swept densely off the node grid.

    Heightfields are included at the same 2 mm bound as the planes because the
    query interpolates cells the way MuJoCo does (main-diagonal triangles), not
    bilinearly. Bilinear left a 30 mm max error on the `random` field.
    """
    config = config_from_dict(raw)
    model, data = _compiled(config, tmp_path)

    worst, worst_at = 0.0, None
    for x in np.linspace(-4.0, 4.0, 9) + _NUDGE_X:
        for y in np.linspace(-4.0, 4.0, 9) + _NUDGE_Y:
            actual = _ray(model, data, float(x), float(y))
            if actual is None:
                continue
            err = surface_height_at(config, float(x), float(y)) - actual
            if abs(err) > abs(worst):
                worst, worst_at = err, (float(x), float(y))
    assert abs(worst) <= 2e-3, f"{raw['terrain']}: off by {worst:+.4f} m at {worst_at}"


@pytest.mark.parametrize(
    "raw",
    [
        {"terrain": "random", "amplitude": 0.12, "resolution": 64, "extent": 12.0},
        {"terrain": "sinusoidal", "amplitude": 0.09, "period": 1.5, "resolution": 64, "extent": 12.0},
    ],
    ids=["random", "sinusoidal"],
)
def test_heightfield_forms_are_node_exact(raw):
    """At grid nodes the query must reproduce the compiled elevation exactly.

    A node is where every interpolation scheme has to agree, so this pins the
    things that can actually be wrong -- origin, scale, axis order and the row
    inversion -- with no tolerance at all. Between nodes MuJoCo triangulates each
    quad while the query samples bilinearly, and on `random` (white noise at cell
    scale) the two differ by up to the local cell-to-cell variation, which for
    amplitude 0.12 is a mean of 39 mm. That is a documented property of the two
    schemes, not an error, so it is not asserted here.
    """
    config = config_from_dict(raw)
    model = build_terrain(config).compile()
    nrow, ncol = int(model.hfield_nrow[0]), int(model.hfield_ncol[0])
    elevation = model.hfield_data.reshape(nrow, ncol) * float(model.hfield_size[0][2])
    half = config.extent / 2.0
    xs, ys = np.linspace(-half, half, ncol), np.linspace(-half, half, nrow)

    worst, worst_at = 0.0, None
    for ci in range(2, ncol - 2, 5):
        for ri in range(2, nrow - 2, 5):
            err = surface_height_at(config, float(xs[ci]), float(ys[ri])) - float(elevation[ri, ci])
            if abs(err) > abs(worst):
                worst, worst_at = err, (ci, ri)
    # 1 um, not 0: MuJoCo stores hfield_data as float32, so a round trip
    # through it carries ~1e-8 m of noise at these amplitudes.
    assert worst == pytest.approx(0.0, abs=1e-6), f"{raw['terrain']}: node (col, row)={worst_at} is off by {worst:+.9f} m"


def test_footprint_query_finds_what_a_point_query_misses(tmp_path):
    """A foot has extent: the point between two stones is not where it rests."""
    config = TerrainConfig(
        terrain_name="surf_stones",
        grid=GridConfig(rows=1, cols=1, tile_size=(8.0, 8.0)),
        border=BorderConfig(width=0.0),
        palette_preset="diverse",
        tiles=[TileConfig(row=0, col=0, type="stepping_stones", params={"seed": 9})],
    )
    surface = TerrainSurface(config)
    stone_top = 0.20  # stone_height default

    # Find a point that sits off a stone but has one within a foot's reach.
    found = None
    for x in np.linspace(-2.5, 2.5, 60):
        for y in np.linspace(-2.5, 2.5, 60):
            point = surface.height_at(float(x), float(y))
            footprint = surface.max_height_in(float(x), float(y), 0.35)
            if point < stone_top / 2 and footprint > stone_top / 2:
                found = (float(x), float(y), point, footprint)
                break
        if found:
            break

    assert found is not None, "no point found where the footprint query differs"
    _x, _y, point, footprint = found
    assert point == pytest.approx(0.0, abs=1e-6)
    assert footprint == pytest.approx(stone_top, abs=1e-6)


def test_reused_surface_matches_the_one_shot_helpers(tmp_path):
    config = _mixed_grid()
    surface = TerrainSurface(config)
    for x, y in [(0.0, 0.0), (-3.3, -3.3), (3.3, 3.3), (1.7, -0.9)]:
        assert surface.height_at(x, y) == surface_height_at(config, x, y)
        assert surface.max_height_in(x, y, 0.2) == max_surface_height_in(config, x, y, 0.2)
