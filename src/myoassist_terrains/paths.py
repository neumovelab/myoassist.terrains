"""Project-path resolution for the myoassist-terrains CLI.

The tool needs to know where the active project's `terrain_config.xml` lives,
so it can write generated terrains alongside it (in `terrain/`) and rewrite
the pointer line in `set-active`. We discover this by walking up from the
current working directory looking for `terrain_config.xml`. Callers can also
pass an explicit root path to bypass discovery.
"""

from __future__ import annotations

import os
from pathlib import Path


_TERRAIN_CONFIG_FILENAME = "terrain_config.xml"
_TERRAIN_LIBRARY_DIRNAME = "terrain"
# Env var that overrides project-root discovery. Kept as MYOASSIST_TERRAINS_ROOT
# for clarity; the legacy MYO_TERRAIN_ROOT name is still honored as a fallback
# for downstream tooling that hasn't migrated yet.
_ENV_ROOT = "MYOASSIST_TERRAINS_ROOT"
_LEGACY_ENV_ROOT = "MYO_TERRAIN_ROOT"


def find_terrain_root(start: Path | None = None) -> Path:
    """Return the directory containing terrain_config.xml.

    Walks upward from `start` (defaults to CWD). Honors the
    `MYOASSIST_TERRAINS_ROOT` environment variable (or its legacy alias
    `MYO_TERRAIN_ROOT`) as an override.
    """
    env_override = os.environ.get(_ENV_ROOT) or os.environ.get(_LEGACY_ENV_ROOT)
    if env_override:
        candidate = Path(env_override).resolve()
        if (candidate / _TERRAIN_CONFIG_FILENAME).exists():
            return candidate
        raise FileNotFoundError(
            f"{_ENV_ROOT}={env_override} does not contain {_TERRAIN_CONFIG_FILENAME}"
        )

    cur = (start or Path.cwd()).resolve()
    while True:
        if (cur / _TERRAIN_CONFIG_FILENAME).exists():
            return cur
        if cur.parent == cur:
            raise FileNotFoundError(
                f"Could not find {_TERRAIN_CONFIG_FILENAME} walking up from {start or Path.cwd()}.\n"
                f"Set {_ENV_ROOT} or run from inside a project tree."
            )
        cur = cur.parent


def terrain_library_dir(root: Path | None = None) -> Path:
    """Return the path to the generated-terrain library directory."""
    root = root or find_terrain_root()
    return root / _TERRAIN_LIBRARY_DIRNAME


def terrain_config_path(root: Path | None = None) -> Path:
    """Return the path to the active-terrain pointer file."""
    root = root or find_terrain_root()
    return root / _TERRAIN_CONFIG_FILENAME


def terrain_style_path(root: Path | None = None) -> Path:
    """Return the path to the user-editable terrain style include."""
    root = root or find_terrain_root()
    return root / "terrain_style.xml"
