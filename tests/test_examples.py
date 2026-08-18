"""Verify every shipped example JSON config builds without error.

This catches drift between the shipped configs under `utils/configs/` and
the package internals (tile param renames, schema changes, etc.) by
exercising the same flow a user would on a fresh checkout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from myoassist_terrains import build_terrain
from myoassist_terrains.config import load_config

CONFIGS_DIR = Path(__file__).resolve().parents[1] / "utils" / "configs"


def _config_paths() -> list[Path]:
    """Every shipped config.

    Deliberately NOT tolerant of a missing directory: an empty `parametrize` list
    collects zero tests and reports success, so this file could silently stop
    checking anything at all if the configs moved.
    """
    assert CONFIGS_DIR.is_dir(), f"shipped configs not found at {CONFIGS_DIR}"
    paths = sorted(CONFIGS_DIR.glob("*.json"))
    assert paths, f"no shipped configs found in {CONFIGS_DIR}"
    return paths


@pytest.mark.parametrize("config_path", _config_paths(), ids=lambda p: p.name)
def test_example_config_builds(config_path: Path, tmp_path: Path):
    """Each shipped JSON config loads, builds, and compiles."""
    cfg = load_config(config_path)

    # Textures in the shipped configs are relative to utils/style/, not
    # the tmp_path. Re-point the texture file to the shipped CONCRETE.png
    # so the build doesn't fail looking for a missing asset.
    if cfg.texture is not None:
        shipped_texture = CONFIGS_DIR.parent / "style" / Path(cfg.texture.file).name
        if shipped_texture.exists():
            cfg.texture.file = str(shipped_texture.resolve()).replace("\\", "/")

    spec = build_terrain(cfg, output_dir=tmp_path)
    model = spec.compile()
    assert model.ngeom > 0


def test_tile_catalog_is_in_sync_with_the_registry():
    """`docs/tiles.md`'s tables are generated; fail if they are stale.

    Four of the review's documentation findings were the same problem: a
    hand-maintained catalog drifting from the code it describes. `density` was
    documented as an area fraction when it is a count per square meter, and
    `boulders` as half-spheres taking a diameter range when they are ellipsoids
    taking radii. Generating the tables removes the drift; this keeps the committed
    file honest about it.
    """
    generator = Path(__file__).resolve().parents[1] / "utils" / "docs" / "_gen_tile_catalog.py"
    result = subprocess.run(
        [sys.executable, str(generator), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
