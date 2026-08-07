"""Tests for the uniform (single-surface) terrain path.

Covers the new top-level `"terrain"` config form (`flat` | `slope` |
`random` | `sinusoidal`) end to end: schema parsing/validation, dispatch
away from the grid/tile path, and geom emission through MjSpec.compile().
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mujoco
import numpy as np
import pytest

from myoassist_terrains import build_terrain
from myoassist_terrains.composer import emit_xml_include
from myoassist_terrains.config import (
    TerrainConfig,
    UniformTerrainConfig,
    _config_from_dict,
    load_config,
)


PLANE = int(mujoco.mjtGeom.mjGEOM_PLANE)
HFIELD = int(mujoco.mjtGeom.mjGEOM_HFIELD)


def _geom_type_counts(model: mujoco.MjModel) -> dict[int, int]:
    counts: dict[int, int] = {}
    for t in model.geom_type:
        counts[int(t)] = counts.get(int(t), 0) + 1
    return counts


def _hfield_physical(model: mujoco.MjModel):
    """Return (physical_heights, dist_from_origin) grids for a compiled
    single-hfield model. Physical height = normalized data * size[2]."""
    nrow = int(model.hfield_nrow[0])
    ncol = int(model.hfield_ncol[0])
    data = model.hfield_data.reshape(nrow, ncol)
    max_z = float(model.hfield_size[0][2])
    half_x = float(model.hfield_size[0][0])
    half_y = float(model.hfield_size[0][1])
    phys = data * max_z
    xs = np.linspace(-half_x, half_x, ncol)
    ys = np.linspace(-half_y, half_y, nrow)
    xx, yy = np.meshgrid(xs, ys)
    dist = np.sqrt(xx * xx + yy * yy)
    return phys, dist


# ---------------------------------------------------------------------------
# Config schema / dispatch


def test_flat_dict_parses_to_uniform_config():
    cfg = _config_from_dict({"terrain": "flat"})
    assert isinstance(cfg, UniformTerrainConfig)
    assert cfg.terrain == "flat"
    assert cfg.terrain_name == "uniform_flat"  # derived default
    assert cfg.palette_preset == "uniform"


def test_slope_dict_parses_deg():
    cfg = _config_from_dict({"terrain": "slope", "deg": 10})
    assert isinstance(cfg, UniformTerrainConfig)
    assert cfg.deg == pytest.approx(10.0)


def test_random_and_sinusoidal_dicts_parse():
    r = _config_from_dict({"terrain": "random", "amplitude": 0.1})
    assert r.terrain == "random"
    assert r.amplitude == pytest.approx(0.1)
    s = _config_from_dict({"terrain": "sinusoidal", "amplitude": 0.05, "period": 1.0})
    assert s.terrain == "sinusoidal"
    assert s.amplitude == pytest.approx(0.05)
    assert s.period == pytest.approx(1.0)


def test_grid_form_still_dispatches_to_terrain_config():
    cfg = _config_from_dict(
        {
            "terrain_name": "g",
            "grid": {"rows": 1, "cols": 1, "tile_size": [1.0, 1.0]},
            "border": {"width": 0.0},
            "tiles": [{"row": 0, "col": 0, "type": "flat"}],
        }
    )
    assert isinstance(cfg, TerrainConfig)


def test_uniform_rejects_unknown_terrain():
    with pytest.raises(ValueError):
        UniformTerrainConfig(terrain="mountain")


def test_uniform_rejects_nonpositive_amplitude():
    with pytest.raises(ValueError):
        UniformTerrainConfig(terrain="random", amplitude=0.0)


def test_uniform_rejects_nonpositive_period():
    with pytest.raises(ValueError):
        UniformTerrainConfig(terrain="sinusoidal", amplitude=0.1, period=0.0)


def test_uniform_rejects_bad_slope_deg():
    with pytest.raises(ValueError):
        UniformTerrainConfig(terrain="slope", deg=95.0)


def test_load_config_uniform_roundtrip(tmp_path: Path):
    payload = {
        "terrain": "sinusoidal",
        "terrain_name": "waves",
        "amplitude": 0.05,
        "period": 1.5,
        "extent": 12.0,
        "resolution": 128,
    }
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    cfg = load_config(path)
    assert isinstance(cfg, UniformTerrainConfig)
    assert cfg.terrain_name == "waves"
    assert cfg.period == pytest.approx(1.5)
    assert cfg.extent == pytest.approx(12.0)
    assert cfg.resolution == 128


# ---------------------------------------------------------------------------
# Build: flat / slope planes


def test_flat_builds_single_plane():
    spec = build_terrain(_config_from_dict({"terrain": "flat"}))
    model = spec.compile()
    assert isinstance(model, mujoco.MjModel)
    assert model.ngeom == 1
    assert _geom_type_counts(model) == {PLANE: 1}


def test_slope_builds_single_plane_tilted_10deg():
    spec = build_terrain(_config_from_dict({"terrain": "slope", "deg": 10}))
    model = spec.compile()
    assert model.ngeom == 1
    assert _geom_type_counts(model) == {PLANE: 1}

    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    # Surface normal is the geom frame's local +z (3rd column of xmat).
    normal = data.geom_xmat[0].reshape(3, 3)[:, 2]
    tilt_deg = math.degrees(math.acos(float(np.clip(normal[2], -1.0, 1.0))))
    assert tilt_deg == pytest.approx(10.0, abs=1e-3)
    # Grade rises in the +x walking direction: dz/dx = -n_x / n_z > 0.
    assert -normal[0] / normal[2] > 0.0


def test_flat_plane_passes_through_origin():
    spec = build_terrain(_config_from_dict({"terrain": "flat"}))
    model = spec.compile()
    assert model.geom("terrain").pos[2] == pytest.approx(0.0)


def test_flat_matches_legacy_matfloor_styling():
    """The default flat plane reproduces the legacy `matfloor` look: an
    infinite plane (size 0 0 0.05), a textured low-reflectance material, and a
    horizon haze matching the ground color."""
    model = build_terrain(_config_from_dict({"terrain": "flat"})).compile()
    # infinite plane (half_x = half_y = 0), 0.05 render grid spacing
    assert list(model.geom("terrain").size) == pytest.approx([0.0, 0.0, 0.05])
    # matfloor material: textured + low reflectance
    reflectance = model.material("myoassist_mat_uniform").reflectance.item()
    assert reflectance == pytest.approx(0.05)
    assert model.ntex >= 1
    # horizon haze == ground color (matfloor rgb1) so the plane fades into itself
    haze = list(model.vis.rgba.haze)[:3]
    assert haze == pytest.approx([0.353, 0.439, 0.529], abs=1e-3)


# ---------------------------------------------------------------------------
# Build: random / sinusoidal heightfields


def test_random_builds_single_hfield_within_amplitude():
    cfg = _config_from_dict({"terrain": "random", "amplitude": 0.1})
    model = build_terrain(cfg).compile()
    assert model.ngeom == 1
    assert _geom_type_counts(model) == {HFIELD: 1}

    phys, dist = _hfield_physical(model)
    # Heights stay within [0, amplitude].
    assert phys.min() >= 0.0
    assert phys.max() <= 0.1 + 1e-6
    # Flat safe zone at the reset point (origin).
    near = dist < 0.5
    assert phys[near].max() < 0.1 * 0.1  # < 10% of amplitude
    # Real variation once outside the safe zone.
    far = dist > 5.0
    assert phys[far].max() > 0.5 * 0.1


def test_sinusoidal_builds_hfield_with_expected_amplitude_and_safe_zone():
    cfg = _config_from_dict({"terrain": "sinusoidal", "amplitude": 0.05, "period": 1.0})
    model = build_terrain(cfg).compile()
    assert model.ngeom == 1
    assert _geom_type_counts(model) == {HFIELD: 1}

    phys, dist = _hfield_physical(model)
    # Peak reaches ~amplitude somewhere on the surface.
    assert phys.max() == pytest.approx(0.05, abs=5e-3)
    assert phys.min() >= 0.0
    # Flat safe zone near the origin.
    near = dist < 0.5
    assert phys[near].max() < 0.1 * 0.05


def test_safe_zone_disabled_when_radius_zero():
    cfg = _config_from_dict(
        {
            "terrain": "sinusoidal",
            "amplitude": 0.05,
            "period": 1.0,
            "safe_zone_radius": 0.0,
        }
    )
    model = build_terrain(cfg).compile()
    phys, dist = _hfield_physical(model)
    # Without a safe zone the surface still varies right up to the origin.
    near = dist < 0.5
    assert phys[near].max() > 0.1 * 0.05


# ---------------------------------------------------------------------------
# XML emission / styling


def test_uniform_hfield_emits_mujocoinclude_with_elevation():
    cfg = _config_from_dict({"terrain": "random", "amplitude": 0.1})
    xml = emit_xml_include(build_terrain(cfg))
    assert xml.startswith("<mujocoinclude")
    assert "<hfield" in xml
    # Data is baked inline (no external PNG), so an `elevation` attr appears.
    assert "elevation" in xml


def test_uniform_uses_shared_material():
    cfg = _config_from_dict({"terrain": "flat"})
    xml = emit_xml_include(build_terrain(cfg))
    assert "myoassist_mat_uniform" in xml


def test_uniform_palette_override_sets_rgba():
    cfg = _config_from_dict({"terrain": "flat", "palette": {"terrain": [0.1, 0.2, 0.3, 1.0]}})
    model = build_terrain(cfg).compile()
    rgba = model.geom("terrain").rgba
    assert rgba[0] == pytest.approx(0.1)
    assert rgba[1] == pytest.approx(0.2)
    assert rgba[2] == pytest.approx(0.3)


def test_uniform_texture_binds(tmp_path: Path):
    PIL = pytest.importorskip("PIL.Image")
    project_root = tmp_path / "project"
    library = project_root / "terrain"
    library.mkdir(parents=True)
    PIL.new("RGB", (8, 8), color=(128, 128, 128)).save(project_root / "tex.png")

    cfg = _config_from_dict({"terrain": "flat", "texture": {"file": "tex.png", "name": "my_tex"}})
    xml = emit_xml_include(build_terrain(cfg, output_dir=library))
    assert 'name="my_tex"' in xml
    assert 'texture="my_tex"' in xml
