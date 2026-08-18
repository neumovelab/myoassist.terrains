"""myoassist_terrains: modular procedural terrain generator for MuJoCo.

Public API surface (stable for v1):
    - `build_terrain(config)`                  -> mujoco.MjSpec
    - `surface_height_at(config, x, y)`        -> walkable surface height
    - `max_surface_height_in(config, x, y, r)` -> highest surface in a footprint
    - `register_tile(...)`    : extension hook for custom tile types
    - CLI: `python -m myoassist_terrains {build, set-active, list, preview}`

The surface queries take a config rather than a compiled model, so a consumer
placing something on the terrain (seating a model at reset, for instance) can ask
the package that owns the geometry instead of collision-probing for it.

The top-level ``__all__`` below is the convenience surface; additional stable
symbols are exposed under their module paths (e.g. ``composer.emit_xml_include`` /
``resolve_tiles`` / ``compute_cell_layouts``, ``config.load_config`` /
``config_from_dict``, ``surface.TerrainSurface``). See ``docs/python-api.md``.
"""

from importlib.metadata import PackageNotFoundError, version

from myoassist_terrains.composer import build_terrain
from myoassist_terrains.registry import register_tile
from myoassist_terrains.surface import max_surface_height_in, surface_height_at

# Read from installed package metadata (pyproject.toml is the single source of truth).
try:
    __version__ = version("myoassist-terrains")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "build_terrain",
    "surface_height_at",
    "max_surface_height_in",
    "register_tile",
    "__version__",
]
