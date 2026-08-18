"""Measure the emitted terrain and hold it to the documented contracts.

Every other test in this suite checks that a config *builds*. Nothing checked
what the resulting surface actually looks like, which is how the boundary
contract came to be violated by the default `stairs` tile and how the velocity
map's height model came to disagree with the geometry it describes.

Two contracts are asserted here, both against ray-cast measurements of the
compiled model rather than against the code that produced it:

1. **Boundary contract** -- every tile presents a flat top at its declared
   `base_height` around its whole perimeter, so connectors join cleanly.
   `gap` is the one deliberate exception: its trench mouth reaches the tile
   edge, which is the point of the tile.
2. **Height model** -- `estimate_surface_height` agrees with the surface the
   tile actually emits. This is what keeps the velocity map honest.
"""

from __future__ import annotations

import numpy as np
import pytest

import mujoco

from myoassist_terrains import build_terrain
from myoassist_terrains.config import BorderConfig, GridConfig, TerrainConfig, TileConfig
from myoassist_terrains.tiles import REGISTRY
from myoassist_terrains.velocity_map import estimate_surface_height


TILE_SIZE = (8.0, 8.0)
BASE_HEIGHT = 0.0

# Keep hfield-backed tiles cheap; the contract does not depend on resolution.
ROUGH_PARAMS = {"seed": 11, "grid_resolution": 64, "vertical_relief": 0.9}

# Perimeter tolerance. Box-geometry tiles land exactly; hfield tiles carry an
# 8-bit PNG quantisation floor of vertical_relief/510 (~1.8 mm at relief 0.9).
PERIMETER_TOL = {"rough": 4e-3}
PERIMETER_TOL_DEFAULT = 1e-3

# Height-model tolerance. Box tiles are exact. `rough` compares a bilinear
# sample of the heightmap against MuJoCo's hfield triangulation, on top of the
# quantisation floor, so it gets more room.
HEIGHT_TOL = {"rough": 2.5e-2}
HEIGHT_TOL_DEFAULT = 1e-3

# `inverted` is offered by these tiles and is selected 50% of the time under
# randomization, so it is part of the default surface, not an edge case.
INVERTED_TILES = ("stairs", "slope", "pyramid_stairs")

# gap deliberately opens its perimeter; see the module docstring.
PERIMETER_EXEMPT = {"gap"}

# Baseline recorded when this fixture was written, before the remediation work.
# Every entry is a known defect with an owning finding id, and every marker is
# strict: once the fix lands the test passes unexpectedly, pytest fails, and the
# marker has to be removed. That keeps the fix/test mapping honest.
PERIMETER_XFAIL = {
    # M4 fixed: stairs auto-fill now reserves one tread of landing per end, and
    # inverted stairs emits a four-sided base frame.
    ("rough", False): "M5: MuJoCo renormalises the hfield PNG, shifting the taper's mid-value off base_height",
}
HEIGHT_XFAIL = {
    ("stairs", False): "M1: missing +1 on the level, and dist measured from the tile edge not the stair span",
    ("stairs", True): "M1: same, mirrored",
    ("slope", False): "M1: the height model ignores cross_ratio, so it reports ramp height over the flat margin",
    ("slope", True): "M1: same, inverted",
    ("pyramid_stairs", False): "M6: int() truncates toward zero, promoting the flat outer margin to level 1",
    ("pyramid_stairs", True): "M6: same, inverted",
    ("rough", False): "M2: the heightmap is sampled y-mirrored relative to the emitted hfield",
    ("boulders", False): "N-X1: scatter tiles report base_height instead of replaying their objects",
    ("discrete_obstacles", False): "N-X1: same",
    ("stepping_stones", False): "N-X1: same",
}


def _case(tile_type: str, inverted: bool, xfails: dict):
    reason = xfails.get((tile_type, inverted))
    marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
    return pytest.param(tile_type, inverted, marks=marks)


def _params(tile_type: str, inverted: bool = False) -> dict:
    params = dict(ROUGH_PARAMS) if tile_type == "rough" else {}
    if inverted:
        params["inverted"] = True
    return params


def _build(tile_type: str, params: dict, tmp_path) -> tuple[mujoco.MjModel, mujoco.MjData, TileConfig]:
    tile = TileConfig(row=0, col=0, type=tile_type, params=params)
    cfg = TerrainConfig(
        terrain_name=f"contract_{tile_type}{'_inv' if params.get('inverted') else ''}",
        grid=GridConfig(rows=1, cols=1, tile_size=TILE_SIZE),
        border=BorderConfig(width=0.0),
        palette_preset="diverse",
        tiles=[tile],
    )
    model = build_terrain(cfg, output_dir=tmp_path).compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, data, tile


def _surface_z(model, data, x: float, y: float, start_z: float = 20.0) -> float | None:
    """Highest surface z at (x, y), or None where the tile emits no geometry."""
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


def _perimeter_probes(inset: float = 2e-3, n: int = 9):
    """Points just inside each of the four tile edges."""
    half_x, half_y = TILE_SIZE[0] / 2 - inset, TILE_SIZE[1] / 2 - inset
    span_x = np.linspace(-half_x * 0.9, half_x * 0.9, n)
    span_y = np.linspace(-half_y * 0.9, half_y * 0.9, n)
    for x in span_x:
        yield float(x), -half_y
        yield float(x), +half_y
    for y in span_y:
        yield -half_x, float(y)
        yield +half_x, float(y)


def _interior_probes(n: int = 7):
    half_x, half_y = TILE_SIZE[0] / 2, TILE_SIZE[1] / 2
    for x in np.linspace(-half_x * 0.92, half_x * 0.92, n):
        for y in np.linspace(-half_y * 0.92, half_y * 0.92, n):
            yield float(x), float(y)


# ---------------------------------------------------------------------------
# 1. Boundary contract


def _contract_cases(xfails: dict):
    for name in sorted(REGISTRY):
        yield _case(name, False, xfails)
        if name in INVERTED_TILES:
            yield _case(name, True, xfails)


@pytest.mark.parametrize(
    "tile_type,inverted",
    list(_contract_cases(PERIMETER_XFAIL)),
    ids=lambda v: (v if isinstance(v, str) else ("inverted" if v else "upright")),
)
def test_perimeter_is_flat_at_base_height(tile_type: str, inverted: bool, tmp_path):
    """Every tile edge sits at base_height, so a connector joins it cleanly."""
    if tile_type in PERIMETER_EXEMPT:
        pytest.skip(f"{tile_type} deliberately opens its perimeter (documented exception)")

    model, data, _ = _build(tile_type, _params(tile_type, inverted), tmp_path)
    tol = PERIMETER_TOL.get(tile_type, PERIMETER_TOL_DEFAULT)

    worst_z, worst_xy, holes = 0.0, None, []
    for x, y in _perimeter_probes():
        z = _surface_z(model, data, x, y)
        if z is None:
            holes.append((x, y))
            continue
        if abs(z - BASE_HEIGHT) > abs(worst_z):
            worst_z, worst_xy = z - BASE_HEIGHT, (x, y)

    assert not holes, f"{tile_type}: perimeter has no geometry at {holes[:3]} ({len(holes)} points)"
    assert abs(worst_z) <= tol, (
        f"{tile_type}{' inverted' if inverted else ''}: perimeter deviates "
        f"{worst_z:+.4f} m from base_height at {worst_xy} (tolerance {tol})"
    )


def test_gap_is_the_only_perimeter_exception(tmp_path):
    """Pin the exemption: gap really does open its perimeter, on purpose."""
    model, data, _ = _build("gap", {}, tmp_path)
    holes = [(x, y) for x, y in _perimeter_probes() if _surface_z(model, data, x, y) is None]
    assert holes, "gap is exempted from the boundary contract but emits a closed perimeter"


# ---------------------------------------------------------------------------
# 2. Height model vs. emitted geometry


@pytest.mark.parametrize(
    "tile_type,inverted",
    list(_contract_cases(HEIGHT_XFAIL)),
    ids=lambda v: (v if isinstance(v, str) else ("inverted" if v else "upright")),
)
def test_surface_height_matches_emitted_geometry(tile_type: str, inverted: bool, tmp_path):
    """The height model agrees with the surface the tile actually emits."""
    params = _params(tile_type, inverted)
    model, data, tile = _build(tile_type, params, tmp_path)
    tol = HEIGHT_TOL.get(tile_type, HEIGHT_TOL_DEFAULT)

    worst_err, worst_at, compared = 0.0, None, 0
    for x, y in _interior_probes():
        actual = _surface_z(model, data, x, y)
        if actual is None:
            continue  # a gap trench, legitimately empty
        estimate = estimate_surface_height(tile, x, y, TILE_SIZE)
        err = estimate - actual
        compared += 1
        if abs(err) > abs(worst_err):
            worst_err, worst_at = err, (x, y)

    assert compared > 0, f"{tile_type}: no probe hit any geometry"
    assert abs(worst_err) <= tol, (
        f"{tile_type}{' inverted' if inverted else ''}: estimate_surface_height is off by "
        f"{worst_err:+.4f} m at {worst_at} over {compared} probes (tolerance {tol})"
    )
