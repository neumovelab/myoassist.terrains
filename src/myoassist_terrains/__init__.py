"""myoassist_terrains: modular procedural terrain generator for MuJoCo.

Public API surface (stable for v1):
    - `build_terrain(config)` -> mujoco.MjSpec
    - `register_tile(...)`    : extension hook for custom tile types
    - CLI: `python -m myoassist_terrains {build, set-active, list, preview}`

The top-level ``__all__`` below is the convenience surface; additional stable
symbols are exposed under their module paths (e.g. ``composer.emit_xml_include`` /
``resolve_tiles`` / ``compute_cell_layouts``, ``config.load_config`` /
``config_from_dict``). See ``docs/python-api.md``.
"""

from myoassist_terrains.composer import build_terrain
from myoassist_terrains.registry import register_tile

__version__ = "0.1.0"

__all__ = ["build_terrain", "register_tile", "__version__"]
