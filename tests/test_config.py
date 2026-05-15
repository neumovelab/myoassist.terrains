"""Validation tests for the JSON-driven config schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myoassist_terrains.config import (
    BorderConfig,
    GridConfig,
    RandomizationSpec,
    TerrainConfig,
    TextureConfig,
    TileConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# GridConfig


def test_grid_config_valid():
    g = GridConfig(rows=3, cols=3, tile_size=(8.0, 8.0))
    assert g.rows == 3
    assert g.cols == 3
    assert g.tile_size == (8.0, 8.0)


@pytest.mark.parametrize("rows,cols", [(0, 1), (1, 0), (-1, 1)])
def test_grid_config_rejects_nonpositive_dims(rows, cols):
    with pytest.raises(ValueError):
        GridConfig(rows=rows, cols=cols, tile_size=(1.0, 1.0))


@pytest.mark.parametrize("tile_size", [(0.0, 1.0), (1.0, -1.0), (1.0,)])
def test_grid_config_rejects_bad_tile_size(tile_size):
    with pytest.raises(ValueError):
        GridConfig(rows=1, cols=1, tile_size=tile_size)


# ---------------------------------------------------------------------------
# BorderConfig


def test_border_config_defaults():
    b = BorderConfig()
    assert b.width == pytest.approx(0.5)
    assert b.match_mode == "min"


def test_border_config_rejects_negative_width():
    with pytest.raises(ValueError):
        BorderConfig(width=-0.1)


def test_border_config_rejects_unknown_match_mode():
    with pytest.raises(ValueError):
        BorderConfig(match_mode="median")


# ---------------------------------------------------------------------------
# TextureConfig


def test_texture_config_defaults():
    t = TextureConfig(file="x.png")
    assert t.name == "terrain_texture"
    assert t.repeat == (4.0, 4.0)
    assert t.texuniform is True


def test_texture_config_rejects_empty_file():
    with pytest.raises(ValueError):
        TextureConfig(file="")


def test_texture_config_rejects_bad_repeat_shape():
    with pytest.raises(ValueError):
        TextureConfig(file="x.png", repeat=(1.0, 1.0, 1.0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RandomizationSpec


def test_randomization_requires_weights():
    with pytest.raises(ValueError):
        RandomizationSpec(weights={})


def test_randomization_rejects_negative_weight():
    with pytest.raises(ValueError):
        RandomizationSpec(weights={"flat": -1.0})


def test_randomization_rejects_all_zero_weights():
    with pytest.raises(ValueError):
        RandomizationSpec(weights={"flat": 0.0, "stairs": 0.0})


# ---------------------------------------------------------------------------
# TerrainConfig


def _minimal_terrain(**overrides) -> TerrainConfig:
    base = dict(
        terrain_name="t",
        grid=GridConfig(rows=2, cols=2, tile_size=(1.0, 1.0)),
        border=BorderConfig(),
        tiles=[TileConfig(row=0, col=0, type="flat")],
    )
    base.update(overrides)
    return TerrainConfig(**base)


def test_terrain_config_valid_minimum():
    cfg = _minimal_terrain()
    assert cfg.terrain_name == "t"
    assert cfg.palette_preset == "diverse"


def test_terrain_config_rejects_empty_name():
    with pytest.raises(ValueError):
        _minimal_terrain(terrain_name="")


def test_terrain_config_rejects_unknown_palette():
    with pytest.raises(ValueError):
        _minimal_terrain(palette_preset="psychedelic")


def test_terrain_config_requires_tiles_or_randomization():
    with pytest.raises(ValueError):
        TerrainConfig(
            terrain_name="t",
            grid=GridConfig(rows=1, cols=1, tile_size=(1.0, 1.0)),
            border=BorderConfig(),
            tiles=[],
            randomization=None,
        )


def test_terrain_config_rejects_out_of_bounds_tile():
    with pytest.raises(ValueError):
        TerrainConfig(
            terrain_name="t",
            grid=GridConfig(rows=2, cols=2, tile_size=(1.0, 1.0)),
            border=BorderConfig(),
            tiles=[TileConfig(row=5, col=0, type="flat")],
        )


# ---------------------------------------------------------------------------
# load_config (file round-trip)


def test_load_config_roundtrip(tmp_path: Path):
    payload = {
        "terrain_name": "t",
        "grid": {"rows": 2, "cols": 2, "tile_size": [1.0, 1.0]},
        "border": {"width": 0.5, "match_mode": "max"},
        "palette_preset": "uniform",
        "texture": {"file": "concrete.png", "repeat": [2.0, 2.0]},
        "tiles": [{"row": 0, "col": 0, "type": "flat", "params": {"height": 0.5}}],
        "randomization": {
            "seed": 7,
            "weights": {"flat": 1.0, "rough": 2.0},
            "param_ranges": {"rough": {"vertical_relief": [0.2, 0.9]}},
        },
    }
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    cfg = load_config(path)
    assert cfg.terrain_name == "t"
    assert cfg.border.match_mode == "max"
    assert cfg.palette_preset == "uniform"
    assert cfg.texture is not None
    assert cfg.texture.repeat == (2.0, 2.0)
    assert cfg.tiles[0].params["height"] == pytest.approx(0.5)
    assert cfg.randomization is not None
    assert cfg.randomization.seed == 7
    assert cfg.randomization.weights == {"flat": 1.0, "rough": 2.0}


def test_load_config_bare_string_texture(tmp_path: Path):
    """The texture field accepts a bare-string shortcut for the file path."""
    payload = {
        "terrain_name": "t",
        "grid": {"rows": 1, "cols": 1, "tile_size": [1.0, 1.0]},
        "border": {"width": 0.0},
        "palette_preset": "uniform",
        "texture": "concrete.png",
        "tiles": [{"row": 0, "col": 0, "type": "flat"}],
    }
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    cfg = load_config(path)
    assert cfg.texture is not None
    assert cfg.texture.file == "concrete.png"
    assert cfg.texture.repeat == (4.0, 4.0)  # default kicks in
