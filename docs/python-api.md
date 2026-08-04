# Python API

```python
from pathlib import Path
import mujoco
from myoassist_terrains import build_terrain, register_tile
from myoassist_terrains.config import load_config
from myoassist_terrains.composer import emit_xml_include

# Load a JSON config and build an MjSpec.
config = load_config(Path("path/to/config.json"))
spec   = build_terrain(config, output_dir=Path("terrain"))

# Compile directly...
model  = spec.compile()

# ...or emit as an XML include for the file-based workflow.
xml = emit_xml_include(spec)
Path("terrain/my_terrain.xml").write_text(xml)
```

Stable public surface:

| Symbol                                            | What it does |
|---------------------------------------------------|--------------|
| `myoassist_terrains.build_terrain(config, output_dir=None)` | Build an `mujoco.MjSpec` from a `TerrainConfig`. |
| `myoassist_terrains.register_tile(name, emit_fn, ...)`      | Register a custom tile type at runtime. |
| `myoassist_terrains.config.load_config(path)`               | Load + validate a JSON config into a `TerrainConfig`. |
| `myoassist_terrains.composer.emit_xml_include(spec)`        | Convert a compiled spec into a `<mujocoinclude>` fragment. |
| `myoassist_terrains.composer.resolve_tiles(config)`         | Resolve explicit + randomized `tiles` into a flat row-major `list[TileConfig]`. |
| `myoassist_terrains.composer.compute_cell_layouts(config)`  | `{(row, col): CellLayout}` giving each cell's world-space center. |
| `myoassist_terrains.tiles.REGISTRY`                          | Read-only dict of tile name -> `TileImpl`. |
| `myoassist_terrains.paths.find_terrain_root()`               | Locate the project root via `terrain_config.xml`. |
| `myoassist_terrains.velocity_map.generate_velocity_map(...)`| Sample a 3D velocity field over a terrain (see [Velocity maps](velocity-maps.md)). |
| `myoassist_terrains.velocity_arrows.add_velocity_overlay(...)`| Inject non-colliding velocity-arrow geoms into an existing scene. |
