# Python API

```python
from pathlib import Path

from myoassist_terrains import build_terrain, max_surface_height_in, surface_height_at
from myoassist_terrains.composer import emit_xml_include
from myoassist_terrains.config import config_from_dict, load_config

# Load a JSON config, or build one from a dict you already hold.
config = load_config(Path("path/to/config.json"))
config = config_from_dict({"terrain": "slope", "deg": 8.0})

spec = build_terrain(config, output_dir=Path("terrain"))

# Compile directly...
model = spec.compile()

# ...or emit an XML include for the file-based workflow.
Path("terrain/my_terrain.xml").write_text(emit_xml_include(spec), encoding="utf-8")

# Ask where the ground is, without compiling anything.
z = surface_height_at(config, x=1.5, y=-2.0)
foot_z = max_surface_height_in(config, x=1.5, y=-2.0, radius=0.12)
```

## Stable public surface

| Symbol | What it does |
|---|---|
| `myoassist_terrains.build_terrain(config, output_dir=None, prune_assets=False)` | Build a `mujoco.MjSpec` from either config form. `output_dir` is where `rough` writes its heightmap and where a `texture` is resolved from. |
| `myoassist_terrains.surface_height_at(config, x, y)` | Walkable surface height at a world coordinate, for either config form. `0.0` beyond the terrain. |
| `myoassist_terrains.max_surface_height_in(config, x, y, radius)` | Highest surface height within `radius`. Use this for anything with extent, such as a foot. |
| `myoassist_terrains.register_tile(name, emit_fn, *, surface_height=None, speed_scale=1.0, ...)` | Register a custom tile type at runtime. |
| `myoassist_terrains.surface.TerrainSurface(config)` | Reusable surface query. Resolves the tiles and layout once, so repeated queries cost microseconds. |
| `myoassist_terrains.config.load_config(path)` | Load and validate a JSON config into a `TerrainConfig` **or** a `UniformTerrainConfig`, depending on the form. |
| `myoassist_terrains.config.config_from_dict(raw)` | The same, from a dict already in memory. |
| `myoassist_terrains.composer.emit_xml_include(spec, *, hfield_relpath_prefix, texture_relpath_prefix)` | Convert a spec into a `<mujocoinclude>` fragment, rewriting asset paths to portable relative ones. |
| `myoassist_terrains.composer.resolve_tiles(config)` | Resolve explicit + randomized `tiles` into a flat row-major `list[TileConfig]`. |
| `myoassist_terrains.composer.compute_cell_layouts(config)` | `{(row, col): CellLayout}` giving each cell's world-space center. |
| `myoassist_terrains.tiles.REGISTRY` | Mutable dict of tile name -> `TileImpl`. `register_tile` writes to it; treat it as read-only unless you mean to. |
| `myoassist_terrains.paths.find_terrain_root(start=None)` | Locate the project root via `terrain_config.xml`. |
| `myoassist_terrains.velocity_map.generate_velocity_map(config, ...)` | Sample a 3D velocity field over a **grid** terrain (see [Velocity maps](velocity-maps.md)). |
| `myoassist_terrains.velocity_arrows.add_velocity_overlay(worldbody, asset, samples, ...)` | Inject non-colliding velocity-arrow geoms into an existing scene. |

## Notes

**`emit_xml_include` carries only `<asset>` and `<worldbody>`,** deliberately. The
consuming model owns the top-level elements: a `<visual>` inside an include merges
into the model, and because `terrain_config.xml` includes the style *before* the
terrain, a terrain-supplied haze would silently override the user's own. A consumer
that wants the full document (haze included) should read `spec.to_xml()`, which is
what `myoassist`'s compose pipeline does.

**Surface queries take a config, not a compiled model.** That is the point: deriving
the ground height from a compiled model means collision-probing, which is what
produced models buried meters into their terrain. Build a `TerrainSurface` once if
you are asking many times; the one-shot helpers rebuild per call.

**`prune_assets` is opt-in.** Heightmap file names are content-addressed, so
re-tuning a `rough` tile leaves the old file behind. Pruning is right for a
project's own terrain library (the CLI passes it) and wrong for a shared asset
directory, where another consumer may still reference the old file.
