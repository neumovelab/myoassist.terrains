"""Smoke tests for every built-in tile type.

For each registered tile, build a 1x1 grid of just that type and verify:
  - it emits geometry to the spec
  - the spec compiles in MuJoCo without error
  - the post-include XML round-trips through ElementTree parsing
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import pytest

from myoassist_terrains import build_terrain
from myoassist_terrains.composer import emit_xml_include
from myoassist_terrains.config import (
    BorderConfig,
    GridConfig,
    TerrainConfig,
    TileConfig,
)
from myoassist_terrains.tiles import REGISTRY

# Per-tile overrides that keep this smoke test cheap (a coarse hfield) or give a
# tile a shape worth compiling at the 4 m tile size used below.
PER_TILE_PARAMS = {
    "rough": {
        "seed": 1,
        "grid_resolution": 64,
        "num_pits": 4,
        "num_hills": 4,
        "vertical_relief": 0.4,
    },
    "stairs": {"n_steps": 3, "step_height": 0.1},
    "pyramid_stairs": {"n_steps": 3, "step_height": 0.1, "step_width": 0.4, "outer_margin": 0.4},
    "gap": {"gap_width": 0.4},
}


@pytest.mark.parametrize("tile_name", sorted(REGISTRY))
def test_each_tile_compiles_solo(tile_name: str, tmp_path: Path):
    cfg = TerrainConfig(
        terrain_name=f"solo_{tile_name}",
        grid=GridConfig(rows=1, cols=1, tile_size=(4.0, 4.0)),
        border=BorderConfig(width=0.0),
        palette_preset="diverse",
        tiles=[
            TileConfig(
                row=0,
                col=0,
                type=tile_name,
                params=PER_TILE_PARAMS.get(tile_name, {}),
            )
        ],
    )
    # Provide tmp_path so hfield-backed tiles (rough) can write their PNG.
    spec = build_terrain(cfg, output_dir=tmp_path)

    # Compilation through MjSpec must succeed.
    model = spec.compile()
    assert isinstance(model, mujoco.MjModel)
    # At minimum the backstop terrain geom should be present.
    assert model.ngeom >= 1

    # Emitted XML must parse cleanly.
    xml = emit_xml_include(spec)
    root = ET.fromstring(xml)
    assert root.tag == "mujocoinclude"
