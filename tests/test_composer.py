"""Composer integration tests.

These exercise the actual `build_terrain()` pipeline against MuJoCo's MjSpec
(no model XML required) so we catch breakages in the path between config ->
geom emission -> XML rewrite.
"""

from __future__ import annotations

import re
from pathlib import Path

import mujoco
import pytest

from myoassist_terrains import build_terrain
from myoassist_terrains.composer import emit_xml_include
from myoassist_terrains.config import (
    BorderConfig,
    GridConfig,
    TerrainConfig,
    TextureConfig,
    TileConfig,
)


def _flat_2x2() -> TerrainConfig:
    return TerrainConfig(
        terrain_name="smoke",
        grid=GridConfig(rows=2, cols=2, tile_size=(5.0, 5.0)),
        border=BorderConfig(width=0.5, match_mode="min"),
        palette_preset="diverse",
        tiles=[
            TileConfig(row=0, col=0, type="flat", params={"height": 0.0}),
            TileConfig(row=0, col=1, type="flat", params={"height": 0.3}),
            TileConfig(row=1, col=0, type="flat", params={"height": 0.0}),
            TileConfig(row=1, col=1, type="flat", params={"height": 0.5}),
        ],
    )


def test_build_terrain_returns_compilable_spec():
    """The composer's output should round-trip through MjSpec.compile()."""
    spec = build_terrain(_flat_2x2())
    model = spec.compile()
    assert isinstance(model, mujoco.MjModel)
    assert model.ngeom > 0  # tiles + connectors + transparent backstop


def test_emit_xml_include_returns_mujocoinclude_root():
    spec = build_terrain(_flat_2x2())
    xml = emit_xml_include(spec)
    assert xml.startswith("<mujocoinclude")
    assert "<asset" in xml
    assert "<worldbody" in xml


def test_terrain_floor_geom_is_emitted():
    """Composer always emits a `terrain` backstop for contact-pair compatibility."""
    spec = build_terrain(_flat_2x2())
    xml = emit_xml_include(spec)
    assert 'name="terrain"' in xml


def test_uniform_palette_registers_single_material():
    cfg = TerrainConfig(
        terrain_name="u",
        grid=GridConfig(rows=1, cols=1, tile_size=(1.0, 1.0)),
        border=BorderConfig(width=0.0),
        palette_preset="uniform",
        tiles=[TileConfig(row=0, col=0, type="flat")],
    )
    spec = build_terrain(cfg)
    xml = emit_xml_include(spec)
    assert "myoassist_mat_uniform" in xml
    # Diverse-mode per-tile materials should NOT appear.
    assert "myoassist_mat_flat" not in xml


def test_diverse_palette_registers_per_tile_materials():
    cfg = TerrainConfig(
        terrain_name="d",
        grid=GridConfig(rows=1, cols=2, tile_size=(1.0, 1.0)),
        border=BorderConfig(width=0.0),
        palette_preset="diverse",
        tiles=[
            TileConfig(row=0, col=0, type="flat"),
            TileConfig(row=0, col=1, type="stairs", params={"n_steps": 3}),
        ],
    )
    spec = build_terrain(cfg)
    xml = emit_xml_include(spec)
    assert "myoassist_mat_flat" in xml
    assert "myoassist_mat_stairs" in xml


def test_rough_tile_emits_hfield_asset(tmp_path: Path):
    """A rough tile should write a .png alongside the terrain XML and reference it."""
    cfg = TerrainConfig(
        terrain_name="rt",
        grid=GridConfig(rows=1, cols=1, tile_size=(4.0, 4.0)),
        border=BorderConfig(width=0.0),
        palette_preset="uniform",
        tiles=[
            TileConfig(
                row=0,
                col=0,
                type="rough",
                params={
                    "seed": 7,
                    "vertical_relief": 0.4,
                    "grid_resolution": 64,
                    "num_pits": 4,
                    "num_hills": 4,
                },
            )
        ],
    )
    spec = build_terrain(cfg, output_dir=tmp_path)
    xml = emit_xml_include(spec)
    assert "<hfield" in xml
    # PNG should be written under output_dir and referenced relatively.
    pngs = list(tmp_path.glob("*.png"))
    assert len(pngs) == 1, f"expected exactly one rough hfield png, got {pngs}"


def test_randomization_fills_uncovered_cells():
    cfg = TerrainConfig(
        terrain_name="r",
        grid=GridConfig(rows=2, cols=2, tile_size=(1.0, 1.0)),
        border=BorderConfig(width=0.0),
        palette_preset="diverse",
        tiles=[TileConfig(row=0, col=0, type="flat")],
        randomization=None,
    )
    # Manually attach a randomization spec so we don't trigger the
    # "must have tiles OR randomization" guard separately.
    from myoassist_terrains.config import RandomizationSpec

    cfg.randomization = RandomizationSpec(seed=1, weights={"flat": 1.0})
    spec = build_terrain(cfg)
    model = spec.compile()
    # 4 cells * (base flat geom) + transparent backstop, plus no connectors.
    # Exact count varies by tile internals; just assert "more than the
    # explicit single-tile scene would produce".
    explicit_only = build_terrain(
        TerrainConfig(
            terrain_name="r2",
            grid=cfg.grid,
            border=cfg.border,
            palette_preset=cfg.palette_preset,
            tiles=[TileConfig(row=0, col=0, type="flat")],
        )
    ).compile()
    assert model.ngeom > explicit_only.ngeom


def test_texture_block_resolves_and_binds(tmp_path: Path):
    """A texture file alongside the project root should bind to the uniform material."""
    PIL = pytest.importorskip("PIL.Image")
    # Place a small PNG one level above tmp_path so the composer's resolver
    # finds it via output_dir.parent / file.
    project_root = tmp_path / "project"
    library = project_root / "terrain"
    library.mkdir(parents=True)
    png_path = project_root / "tex.png"
    PIL.new("RGB", (8, 8), color=(128, 128, 128)).save(png_path)

    cfg = TerrainConfig(
        terrain_name="tx",
        grid=GridConfig(rows=1, cols=1, tile_size=(1.0, 1.0)),
        border=BorderConfig(width=0.0),
        palette_preset="uniform",
        texture=TextureConfig(file="tex.png", name="my_tex"),
        tiles=[TileConfig(row=0, col=0, type="flat")],
    )

    spec = build_terrain(cfg, output_dir=library)
    xml = emit_xml_include(spec)
    assert 'name="my_tex"' in xml
    assert 'texture="my_tex"' in xml


def test_emitted_paths_distinguish_texture_and_hfield(tmp_path: Path):
    """Texture paths point at project root (`../`), hfield paths into the
    terrain library (`../terrain/`).

    Regression test for a bug where the post-emit rewrite blanket-pointed
    every `.png` file= attribute under `../terrain/`, breaking user textures
    that live at project root next to terrain_style.xml.
    """
    PIL = pytest.importorskip("PIL.Image")
    project_root = tmp_path / "project"
    library = project_root / "terrain"
    library.mkdir(parents=True)
    PIL.new("RGB", (8, 8), color=(128, 128, 128)).save(project_root / "tex.png")

    cfg = TerrainConfig(
        terrain_name="paths",
        grid=GridConfig(rows=1, cols=1, tile_size=(4.0, 4.0)),
        border=BorderConfig(width=0.0),
        palette_preset="uniform",
        texture=TextureConfig(file="tex.png", name="my_tex"),
        tiles=[
            TileConfig(
                row=0,
                col=0,
                type="rough",
                params={
                    "seed": 5,
                    "grid_resolution": 64,
                    "num_pits": 2,
                    "num_hills": 2,
                    "vertical_relief": 0.3,
                },
            )
        ],
    )

    spec = build_terrain(cfg, output_dir=library)
    xml = emit_xml_include(spec)

    # Texture should resolve from project root (one ../ from the consumer
    # model's parent dir), NOT from inside the terrain library.
    assert 'file="../tex.png"' in xml
    assert 'file="../terrain/tex.png"' not in xml
    # Hfield assets live in the library so they should keep the ../terrain/ prefix.
    # The basename carries a content digest (so a rebuild cannot be served a
    # stale heightfield from MuJoCo's per-process asset cache), hence the regex.
    assert re.search(r'file="\.\./terrain/paths_rough_r0c0_[0-9a-f]{8}\.png"', xml), xml


def test_unknown_tile_type_raises():
    cfg = TerrainConfig(
        terrain_name="bad",
        grid=GridConfig(rows=1, cols=1, tile_size=(1.0, 1.0)),
        border=BorderConfig(width=0.0),
        tiles=[TileConfig(row=0, col=0, type="not_a_real_tile")],
    )
    with pytest.raises(KeyError):
        build_terrain(cfg)
