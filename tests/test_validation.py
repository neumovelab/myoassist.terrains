"""Configs that used to fail silently, or fail deep, now fail here with a message.

Each test names the class of mistake it guards. The common thread is that a
terrain config is an experiment description: a typo that silently changes the
ground is worse than a crash, because the run still produces numbers.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from myoassist_terrains import build_terrain
from myoassist_terrains.config import (
    BorderConfig,
    GridConfig,
    TerrainConfig,
    TileConfig,
    config_from_dict,
)


def _grid(**overrides) -> dict:
    base = {
        "terrain_name": "v",
        "grid": {"rows": 2, "cols": 2, "tile_size": [8.0, 8.0]},
        "border": {"width": 0.5},
        "tiles": [{"row": 0, "col": 0, "type": "flat", "params": {"height": 0.0}}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Silent substitution: the config asked for something it did not get


@pytest.mark.parametrize(
    "raw,bad_key",
    [
        ({"terrain": "slope", "dge": 8.0}, "dge"),
        ({"terrain": "random", "amplitud": 0.35}, "amplitud"),
        ({"terrain": "flat", "resolutoin": 128}, "resolutoin"),
    ],
)
def test_typo_in_a_uniform_key_is_rejected(raw, bad_key):
    """`{"terrain": "slope", "dge": 8}` used to build flat ground and pass.

    That is the worst failure mode available: the run completes and reports
    numbers for a course that was never built.
    """
    with pytest.raises(ValueError, match=bad_key):
        config_from_dict(raw)


@pytest.mark.parametrize("bad_key", ["boarder", "pallete_preset", "textrue", "tils"])
def test_typo_in_a_grid_key_is_rejected(bad_key):
    with pytest.raises(ValueError, match=bad_key):
        config_from_dict(_grid(**{bad_key: {}}))


def test_underscore_keys_are_allowed_as_comments():
    """The bundled render configs use `_comment`; keep that working."""
    cfg = config_from_dict(_grid(_comment="a note", _author="someone"))
    assert cfg.terrain_name == "v"


def test_typo_in_a_tile_param_names_the_tile_and_cell():
    config = TerrainConfig(
        terrain_name="v",
        grid=GridConfig(rows=1, cols=1, tile_size=(8.0, 8.0)),
        border=BorderConfig(width=0.0),
        tiles=[TileConfig(row=0, col=0, type="flat", params={"heght": 0.5})],
    )
    with pytest.raises(ValueError, match=r"flat.*row=0.*col=0.*heght"):
        build_terrain(config)


# ---------------------------------------------------------------------------
# Geometry the config could not actually produce


def test_duplicate_cell_is_rejected():
    """Two tiles in one cell used to overlap, or collide on a MuJoCo geom name."""
    with pytest.raises(ValueError, match="Duplicate tile"):
        config_from_dict(
            _grid(
                tiles=[
                    {"row": 0, "col": 0, "type": "flat"},
                    {"row": 0, "col": 0, "type": "stairs"},
                ]
            )
        )


@pytest.mark.parametrize(
    "params,match",
    [
        ({"inverted": True, "outer_margin": 0.0}, "outer_margin"),
        ({"outer_margin": 5.0}, "outer_margin"),
    ],
)
def test_pyramid_stairs_rejects_a_degenerate_margin(params, match):
    """These used to reach MuJoCo as `size 1 must be positive in geom`."""
    config = TerrainConfig(
        terrain_name="v",
        grid=GridConfig(rows=1, cols=1, tile_size=(8.0, 8.0)),
        border=BorderConfig(width=0.0),
        tiles=[TileConfig(row=0, col=0, type="pyramid_stairs", params={"n_steps": 3, **params})],
    )
    with pytest.raises(ValueError, match=match):
        build_terrain(config)


# ---------------------------------------------------------------------------
# Settings that were computed and then discarded


def test_texture_outside_uniform_mode_is_rejected():
    """A texture in diverse mode was dropped, and its file never even checked."""
    with pytest.raises(ValueError, match="palette_preset='uniform'"):
        build_terrain(config_from_dict(_grid(palette_preset="diverse", texture="nope.png")))


def test_per_type_palette_in_uniform_mode_is_rejected():
    with pytest.raises(ValueError, match="per-type palette"):
        build_terrain(config_from_dict(_grid(palette_preset="uniform", palette={"flat": [1, 0, 0, 1]})))


def test_uniform_palette_override_is_honoured():
    """One global override under "uniform" applies, matching the uniform-terrain path."""
    model = build_terrain(
        config_from_dict(_grid(palette_preset="uniform", palette={"uniform": [0.2, 0.4, 0.6, 1.0]}))
    ).compile()
    rgba = model.geom("flat_r0c0_box").rgba
    assert (round(float(rgba[0]), 3), round(float(rgba[1]), 3), round(float(rgba[2]), 3)) == (0.2, 0.4, 0.6)


def test_custom_preset_requires_every_placed_colour():
    """`custom` used to be byte-identical to `diverse`, so it meant nothing."""
    with pytest.raises(ValueError, match="requires a palette entry"):
        build_terrain(
            config_from_dict(
                _grid(
                    palette_preset="custom",
                    palette={"flat": [1, 0, 0, 1]},
                    tiles=[
                        {"row": 0, "col": 0, "type": "flat"},
                        {"row": 0, "col": 1, "type": "stairs"},
                    ],
                )
            )
        )


def test_custom_preset_accepts_a_complete_palette():
    model = build_terrain(
        config_from_dict(
            _grid(
                palette_preset="custom",
                palette={"flat": [1.0, 0.0, 0.0, 1.0], "stairs": [0.0, 1.0, 0.0, 1.0]},
                tiles=[
                    {"row": 0, "col": 0, "type": "flat"},
                    {"row": 0, "col": 1, "type": "stairs", "params": {"n_steps": 3}},
                ],
            )
        )
    ).compile()
    assert round(float(model.geom("flat_r0c0_box").rgba[0]), 3) == 1.0


# ---------------------------------------------------------------------------
# Randomization specs that could not do what they said


def test_list_valued_param_cannot_be_randomized():
    """`size_range: [0.2, 0.6]` reads as a range and used to yield a bare float,
    which then blew up inside the tile as a TypeError."""
    with pytest.raises(ValueError, match="cannot be randomized"):
        build_terrain(
            config_from_dict(
                _grid(
                    tiles=[],
                    randomization={
                        "seed": 1,
                        "weights": {"boulders": 1.0},
                        "param_ranges": {"boulders": {"size_range": [0.2, 0.6]}},
                    },
                )
            )
        )


def test_reversed_float_range_is_rejected():
    """numpy silently samples [hi, lo) for swapped bounds, so floats used to pass
    where ints raised."""
    with pytest.raises(ValueError, match=r"hi .* < lo"):
        build_terrain(
            config_from_dict(
                _grid(
                    tiles=[],
                    randomization={
                        "seed": 1,
                        "weights": {"slope": 1.0},
                        "param_ranges": {"slope": {"angle_deg": [25.0, 5.0]}},
                    },
                )
            )
        )


# ---------------------------------------------------------------------------
# Output paths


@pytest.mark.parametrize(
    "name",
    ["../escaped", "sub/dir", "..", ".", "a\\b", "..\\up"],
)
def test_terrain_name_must_be_a_bare_filename(name):
    """`terrain_name` becomes `terrain/<name>.xml`, so a separator escaped the library.

    The backslash cases run on every platform on purpose. `Path` only treats a
    backslash as a separator on Windows, so a check that leaned on it made these names
    an error on Windows and legal on Linux, which is how this first failed in CI. A
    config is a shared artifact and gets built on both.
    """
    with pytest.raises(ValueError, match="bare file name"):
        config_from_dict(_grid(terrain_name=name))


# ---------------------------------------------------------------------------
# Assets


def test_rebuilding_under_one_name_does_not_reuse_stale_elevation():
    """MuJoCo caches decoded assets by path, so a name that ignored content used
    to serve the first build's heightfield to every later build in the process."""
    tmp = pathlib.Path(tempfile.mkdtemp())

    def build(seed: int):
        config = TerrainConfig(
            terrain_name="same",
            grid=GridConfig(rows=1, cols=1, tile_size=(8.0, 8.0)),
            border=BorderConfig(width=0.0),
            tiles=[
                TileConfig(
                    row=0,
                    col=0,
                    type="rough",
                    params={"seed": seed, "grid_resolution": 32, "relief_mode": "up"},
                )
            ],
        )
        model = build_terrain(config, output_dir=tmp).compile()
        return model.hfield_data.copy()

    first, second = build(1), build(999)
    assert not (first == second).all(), "the second build was served the first build's heightfield"
    # Identical content must still reuse one file rather than accumulate copies.
    assert (build(1) == first).all()
