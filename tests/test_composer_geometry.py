"""Composer internals that had no coverage: layouts, connectors, XML emission.

`docs/development.md` claimed the suite covered "the composer (layouts, ...)". It
did not: `compute_cell_layouts` had no test, connector heights were never checked
against `match_mode`, `emit_xml_include`'s path prefixes were never exercised, and
the uniform terrain's XML path was untested.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest

from myoassist_terrains import build_terrain
from myoassist_terrains.composer import compute_cell_layouts, emit_xml_include, resolve_tiles
from myoassist_terrains.config import (
    BorderConfig,
    GridConfig,
    RandomizationSpec,
    TerrainConfig,
    TileConfig,
    config_from_dict,
)

# ---------------------------------------------------------------------------
# Layout


def test_cell_layout_matches_the_documented_convention():
    """Grid centred on the origin, row 0 / col 0 at the most negative (x, y),
    rows increasing in +y and cols in +x, with borders added between cells."""
    config = TerrainConfig(
        terrain_name="layout",
        grid=GridConfig(rows=2, cols=3, tile_size=(4.0, 6.0)),
        border=BorderConfig(width=1.0),
        tiles=[TileConfig(row=0, col=0, type="flat")],
        randomization=RandomizationSpec(seed=0, weights={"flat": 1.0}),
    )
    layouts = compute_cell_layouts(config)
    assert set(layouts) == {(r, c) for r in range(2) for c in range(3)}

    # cols: 3 tiles of 4 m + 2 borders of 1 m = 14 m wide, centred -> -5, 0, +5
    assert [layouts[(0, c)].center_x for c in range(3)] == pytest.approx([-5.0, 0.0, 5.0])
    # rows: 2 tiles of 6 m + 1 border of 1 m = 13 m long, centred -> -3.5, +3.5
    assert [layouts[(r, 0)].center_y for r in range(2)] == pytest.approx([-3.5, 3.5])
    # row 0 / col 0 is the most negative corner
    assert layouts[(0, 0)].center_x == min(layout.center_x for layout in layouts.values())
    assert layouts[(0, 0)].center_y == min(layout.center_y for layout in layouts.values())


def test_resolved_tiles_are_row_major():
    config = TerrainConfig(
        terrain_name="order",
        grid=GridConfig(rows=2, cols=2, tile_size=(2.0, 2.0)),
        border=BorderConfig(width=0.0),
        # Deliberately out of order, and without randomization, which is the path
        # that used to skip the sort while the docstring promised row-major.
        tiles=[
            TileConfig(row=1, col=1, type="flat"),
            TileConfig(row=0, col=1, type="flat"),
            TileConfig(row=1, col=0, type="flat"),
            TileConfig(row=0, col=0, type="flat"),
        ],
    )
    assert [(t.row, t.col) for t in resolve_tiles(config)] == [(0, 0), (0, 1), (1, 0), (1, 1)]


# ---------------------------------------------------------------------------
# Connectors


@pytest.mark.parametrize(
    "match_mode,expected",
    [("min", 0.0), ("max", 0.6), ("mean", 0.3)],
)
def test_connector_top_follows_match_mode(match_mode, expected, tmp_path):
    """The strip between two cells is negotiated, and the negotiation is measured
    here against the emitted geometry rather than trusted."""
    config = TerrainConfig(
        terrain_name=f"conn_{match_mode}",
        grid=GridConfig(rows=1, cols=2, tile_size=(6.0, 6.0)),
        border=BorderConfig(width=0.8, match_mode=match_mode),
        tiles=[
            TileConfig(row=0, col=0, type="flat", params={"height": 0.0}),
            TileConfig(row=0, col=1, type="flat", params={"height": 0.6}),
        ],
    )
    model = build_terrain(config, output_dir=tmp_path).compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    geomid = np.zeros(1, dtype=np.int32)
    dist = mujoco.mj_ray(
        model,
        data,
        np.array([0.0, 0.371, 20.0]),  # over the strip, off the cell boundary
        np.array([0.0, 0.0, -1.0]),
        None,
        1,
        -1,
        geomid,
    )
    assert dist >= 0
    assert 20.0 - dist == pytest.approx(expected, abs=1e-3)
    assert (model.geom(int(geomid[0])).name or "").startswith("connector_")


def test_zero_border_emits_no_connectors(tmp_path):
    config = TerrainConfig(
        terrain_name="no_conn",
        grid=GridConfig(rows=1, cols=2, tile_size=(4.0, 4.0)),
        border=BorderConfig(width=0.0),
        tiles=[TileConfig(row=0, col=c, type="flat") for c in range(2)],
    )
    model = build_terrain(config, output_dir=tmp_path).compile()
    names = [model.geom(i).name or "" for i in range(model.ngeom)]
    assert not [n for n in names if n.startswith("connector_")]


# ---------------------------------------------------------------------------
# XML emission


def test_asset_path_prefixes_are_configurable(tmp_path):
    """Both prefixes are public parameters and neither was exercised."""
    project = tmp_path / "project"
    (project / "terrain").mkdir(parents=True)
    pytest.importorskip("PIL.Image").new("RGB", (8, 8), (128, 128, 128)).save(project / "tex.png")

    config = config_from_dict(
        {
            "terrain_name": "prefixes",
            "grid": {"rows": 1, "cols": 1, "tile_size": [4.0, 4.0]},
            "border": {"width": 0.0},
            "palette_preset": "uniform",
            "texture": {"file": "tex.png", "name": "tex"},
            "tiles": [
                {
                    "row": 0,
                    "col": 0,
                    "type": "rough",
                    "params": {"seed": 2, "grid_resolution": 32},
                }
            ],
        }
    )
    spec = build_terrain(config, output_dir=project / "terrain")
    xml = emit_xml_include(spec, hfield_relpath_prefix="assets/hf", texture_relpath_prefix="assets/tex")
    files = re.findall(r'file="([^"]+)"', xml)
    assert any(f.startswith("assets/hf/") and f.endswith(".png") for f in files), files
    assert any(f.startswith("assets/tex/") and f.endswith("tex.png") for f in files), files


def test_include_carries_only_assets_and_worldbody():
    """A deliberate contract: the consuming model owns the top-level elements.

    A `<visual>` inside an include merges into the consuming model, and because
    terrain_config.xml includes the style *before* the terrain, a terrain-supplied
    haze would silently override the user's own. So the uniform path sets haze on
    the spec (for in-memory consumers, which read `to_xml()`) but the include
    fragment must not carry it.
    """
    spec = build_terrain(config_from_dict({"terrain": "flat"}))
    assert list(spec.visual.rgba.haze)[:3] != [1.0, 1.0, 1.0]  # the spec does set it

    root = ET.fromstring(emit_xml_include(spec))
    assert root.tag == "mujocoinclude"
    assert {child.tag for child in root} <= {"asset", "worldbody"}
    assert "haze" not in emit_xml_include(spec)


def test_uniform_terrain_include_reloads_as_a_model():
    """The uniform XML path was only ever checked as a compiled spec."""
    spec = build_terrain(config_from_dict({"terrain": "sinusoidal", "amplitude": 0.05, "resolution": 32}))
    fragment = emit_xml_include(spec)
    wrapped = f'<mujoco model="w">{fragment[len("<mujocoinclude>") : -len("</mujocoinclude>")]}</mujoco>'
    model = mujoco.MjModel.from_xml_string(wrapped)
    assert model.nhfield == 1
    assert model.ngeom == 1
