# myoassist.terrains

**Modular procedural terrain generator for MuJoCo, designed to be used by [MyoAssist](https://github.com/neumovelab/myoassist) and other musculoskeletal-simulation projects within [MyoSuite](https://myosuite.readthedocs.io/en/latest/).**

`myoassist_terrains` turns a small JSON description of a grid layout into a
ready-to-include MuJoCo MJCF fragment containing tiles, connectors, materials
and (optionally) heightfield assets. It supports explicit per-cell placement,
weighted-random sampling per cell, parametric variation of every tile type,
and a single shared texture for uniform-palette terrains.

```
┌──────────────────────────────────────────────────────────────────┐
│  JSON config  ──►  build_terrain()  ──►  MjSpec  ──►  XML include│
│                       (Python API)          (compose)    (CLI)   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Table of contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Concepts](#concepts)
- [Tile catalog](#tile-catalog)
- [Configuration schema](#configuration-schema)
- [CLI reference](#cli-reference)
- [Python API](#python-api)
- [Velocity maps](#velocity-maps)
- [Project layout for users](#project-layout-for-users)
- [Utilities and example configs](#utilities-and-example-configs)
- [Extending: adding a custom tile type](#extending-adding-a-custom-tile-type)
- [Development](#development)

---

## Installation

The package is published as a normal Python package and is utilized via
`pip install -e .` (editable) or `pip install .` for a frozen build.

```bash
git clone https://github.com/neumovelab/myoassist.terrains.git
cd myoassist.terrains
pip install -e .

# Optional extras
pip install -e ".[render]"   # adds mediapy for ensemble renders
pip install -e ".[dev]"      # adds pytest for unit tests
```

Requires Python `>=3.10` and `mujoco>=3.3.3`.

---

## Quick start

Author a config:

```json
{
  "terrain_name": "first_terrain",
  "grid":   { "rows": 2, "cols": 2, "tile_size": [10.0, 10.0] },
  "border": { "width": 0.5, "match_mode": "min" },
  "palette_preset": "diverse",
  "tiles": [
    { "row": 0, "col": 0, "type": "flat",   "params": { "height": 0.0 } },
    { "row": 0, "col": 1, "type": "stairs", "params": { "n_steps": 6, "step_height": 0.18 } },
    { "row": 1, "col": 0, "type": "slope",  "params": { "angle_deg": 18.0 } },
    { "row": 1, "col": 1, "type": "rough",  "params": { "seed": 42, "vertical_relief": 0.8 } }
  ]
}
```

Build it from a project that contains a `terrain_config.xml` pointer:

```bash
cd my_user_project        # contains terrain_config.xml + terrain_style.xml
myoassist-terrains build path/to/first_terrain.json --activate
```

The CLI writes `terrain/first_terrain.xml` into the project directory and (with
`--activate`) updates the `<include file="terrain/first_terrain.xml"/>` line in
`terrain_config.xml`. Any user model that includes `terrain_config.xml`
now sees the new terrain.

Preview it without a user model:

```bash
myoassist-terrains preview first_terrain
python -m mujoco.viewer --mjcf=terrain/first_terrain_preview.xml
```

---

## Concepts

### Grid

A terrain is a `rows × cols` grid of square or rectangular **tiles** with
configurable `tile_size = (width_x, length_y)`. The grid is centred at the
world origin. Cell `(row=0, col=0)` is at the most-negative `(x, y)` corner;
rows increase in `+y`, cols increase in `+x`.

### Tiles

Each cell is filled by one **tile type** chosen from the registry. Tile
modules supply `DEFAULT_PARAMS`, `PARAM_RANGES`, and an `emit(...)` function
that adds geoms (and optionally a heightfield asset) to a MuJoCo `MjSpec`.

### Connectors

Cells are separated by a flat connector strip of `border.width` metres
(set to `0` to make tiles touch). Edge connectors and corner pieces are
generated automatically; their top face is matched to neighbouring tile
heights via `border.match_mode = "min" | "max" | "mean"`. Connectors span
all the way down to `BASELINE_Z = -2.0`, so adjacent height differences read
as clean step risers rather than floating shelves.

### Boundary contract

Every tile presents a **flat top at its declared base height** around its full
perimeter (the `flat-at-base` v1 contract). This lets connectors join cleanly
regardless of what's happening in the middle of the tile.

### Palette

Three palette modes (`palette_preset`):

| Mode      | Behaviour                                                                                          |
|-----------|----------------------------------------------------------------------------------------------------|
| `diverse` | Each tile type renders in its own default colour. Easy to read at-a-glance during config tuning.   |
| `uniform` | Every tile shares the colour of `terrain_mat` declared in `terrain_style.xml` (plus optional texture). Good for final renders. |
| `custom`  | Like `diverse` but user-supplied per-type rgba overrides in `palette`.                             |

### Texture (uniform mode only)

A single 2D texture can be bound to the uniform material via a `"texture"`
block on the config. Useful for concrete / asphalt / dirt finishes on
final-render terrains.

### Randomisation

Cells not covered by an explicit `tiles` entry are filled by sampling a
tile type from `randomization.weights`. Each sampled tile's parameters are
drawn from either `randomization.param_ranges[type]` (user-supplied) or the
tile's built-in `PARAM_RANGES`. Explicit `tiles` and `randomization` can
coexist — explicit placements win, the rest is sampled.

---

## Tile catalog

All angles in radians unless noted. All sizes / heights in metres.

### `flat`
A flat-topped box at a fixed height.

| Parameter | Default | Range / type | Description |
|-----------|---------|--------------|-------------|
| `height`  | `0.0`   | float        | Top face z-coordinate (offset above grid plane). |

### `stairs`
A staircase rising to a central peak then mirroring down. Supports an `inverted` pit variant.

| Parameter      | Default     | Range / type        | Description |
|----------------|-------------|---------------------|-------------|
| `step_height`  | `0.15`      | float, `(0.08, 0.25)` | Riser height per step. |
| `step_width`   | `None`      | float \| `None`     | Tread depth. `None` -> tile auto-fits all `n_steps`. |
| `n_steps`      | `6`         | int, `(3, 12)`      | Number of risers from base to peak. |
| `axis`         | `"y"`       | `"x"` \| `"y"`      | Axis the staircase runs along. |
| `peak_width`   | `0.4`       | float, `(0.2, 0.5)` | Width of the flat plateau at the top. |
| `return_mode`  | `"mirror"`  | str                 | How the descending half is constructed. |
| `cross_ratio`  | `0.9`       | float               | Fraction of the perpendicular axis covered by tread. |
| `inverted`     | `False`     | bool                | If `True`, stairs descend into a pit and mirror back up. |
| `base_height`  | `0.0`       | float               | z-coordinate of the tile's flat-edge base. |

### `slope`
A flat ramp that climbs along one axis with optional plateau at the peak.

| Parameter        | Default      | Range / type            | Description |
|------------------|--------------|-------------------------|-------------|
| `angle_deg`      | `12.0`       | float, `(5.0, 25.0)`    | Incline angle in degrees. |
| `axis`           | `"y"`        | `"x"` \| `"y"`          | Axis the slope rises along. |
| `direction`      | `"mirror"`   | str                     | How the falling half is constructed. |
| `plateau_ratio`  | `0.1`        | float, `(0.05, 0.3)`    | Fraction of tile length given to the flat peak. |
| `cross_ratio`    | `0.9`        | float                   | Fraction of perpendicular axis covered by the ramp. |
| `inverted`       | `False`      | bool                    | If `True`, ramp descends into a pit and rises back. |
| `base_height`    | `0.0`        | float                   | z-coordinate of the tile's flat-edge base. |

### `pyramid_stairs`
Concentric square stairs rising to (or descending from) a central platform.

| Parameter        | Default | Range / type          | Description |
|------------------|---------|-----------------------|-------------|
| `step_height`    | `0.2`   | float, `(0.1, 0.3)`   | Riser height per step. |
| `step_width`     | `0.5`   | float, `(0.3, 0.8)`   | Tread depth (radial). |
| `n_steps`        | `5`     | int, `(3, 8)`         | Number of concentric steps. |
| `outer_margin`   | `0.5`   | float, `(0.2, 1.0)`   | Flat band between the tile edge and the first step. |
| `inverted`       | `False` | bool                  | If `True`, stairs descend into a central pit. |
| `base_height`    | `0.0`   | float                 | z-coordinate of the tile's flat-edge base. |

### `rough`
Heightfield-backed mixed terrain (basins + plateaus + hills + detail noise).
Writes a `.png` heightmap to the terrain library directory.

| Parameter           | Default      | Range / type        | Description |
|---------------------|--------------|---------------------|-------------|
| `seed`              | `0`          | int, `(0, 1e6)`     | RNG seed for the heightmap. |
| `vertical_relief`   | `0.8`        | float, `(0.1, 1.5)` | Total `[min, max]` heightmap range, scaled by `hfield_size_z`. |
| `grid_resolution`   | `256`        | int                 | Heightmap resolution in pixels per side. |
| `num_pits`          | `18`         | int, `(0, 30)`      | Number of gaussian pit features blended in. |
| `num_hills`         | `24`         | int, `(0, 30)`      | Number of gaussian hill features blended in. |
| `terrace_levels`    | `5`          | int, `(1, 9)`       | Plateau quantization levels. |
| `pit_threshold`     | `0.33`       | float               | Selector cutoff that switches macro region to "pit". |
| `plateau_threshold` | `0.68`       | float               | Selector cutoff that switches macro region to "plateau". |
| `edge_taper_frac`   | `0.1`        | float               | Fractional band over which heights taper to 0 at tile edge (preserves the flat-at-base contract). |
| `relief_mode`       | `"centered"` | `"centered"` \| `"up"` \| `"down"` | Whether features go ± around base, only up, or only down. |
| `base_height`       | `0.0`        | float               | z-coordinate of the tile's flat-edge base. |

### `discrete_obstacles`
Randomly placed boxes at random heights (cones, blocks).

| Parameter      | Default       | Range / type         | Description |
|----------------|---------------|----------------------|-------------|
| `density`      | `0.4`         | float, `(0.1, 1.0)`  | Approximate fraction of tile area covered by obstacles. |
| `size_range`   | `[0.2, 0.5]`  | `[lo, hi]`           | Min/max obstacle footprint size in metres. |
| `height_range` | `[0.1, 0.4]`  | `[lo, hi]`           | Min/max obstacle height in metres. |
| `edge_margin`  | `0.5`         | float, `(0.2, 1.0)`  | Keep obstacles this far from the tile edge. |
| `seed`         | `0`           | int                  | RNG seed. |
| `base_height`  | `0.0`         | float                | z-coordinate of the tile's flat-edge base. |

### `stepping_stones`
A regular grid of small raised stones with optional jitter.

| Parameter       | Default | Range / type         | Description |
|-----------------|---------|----------------------|-------------|
| `rows`          | `4`     | int, `(2, 8)`        | Number of stones along the y-axis. |
| `cols`          | `4`     | int, `(2, 8)`        | Number of stones along the x-axis. |
| `stone_size`    | `0.6`   | float, `(0.3, 1.0)`  | Stone footprint size in metres. |
| `stone_height`  | `0.2`   | float, `(0.05, 0.4)` | Height of each stone above base. |
| `jitter_frac`   | `0.2`   | float, `(0.0, 0.4)`  | Random offset as a fraction of stone spacing. |
| `edge_margin`   | `0.5`   | float                | Keep stones this far from the tile edge. |
| `seed`          | `0`     | int                  | RNG seed. |
| `base_height`   | `0.0`   | float                | z-coordinate of the tile's flat-edge base. |

### `boulders`
Randomly placed half-sphere boulders.

| Parameter      | Default      | Range / type        | Description |
|----------------|--------------|---------------------|-------------|
| `density`      | `0.3`        | float, `(0.05, 0.8)`| Approximate fraction of tile area covered by boulders. |
| `size_range`   | `[0.2, 0.6]` | `[lo, hi]`          | Min/max boulder diameter in metres. |
| `edge_margin`  | `0.5`        | float, `(0.2, 1.0)` | Keep boulders this far from the tile edge. |
| `seed`         | `0`          | int                 | RNG seed. |
| `base_height`  | `0.0`        | float               | z-coordinate of the tile's flat-edge base. |

### `gap`
A linear gap cut through the tile (no geom in the gap band).

| Parameter     | Default | Range / type       | Description |
|---------------|---------|--------------------|-------------|
| `gap_width`   | `0.5`   | float, `(0.1, 1.0)`| Width of the gap in metres. |
| `axis`        | `"y"`   | `"x"` \| `"y"`     | Axis the gap runs along. |
| `base_height` | `0.0`   | float              | z-coordinate of the tile's flat-edge base. |

---

## Configuration schema

```jsonc
{
  // Required. Output XML will be written as terrain/<terrain_name>.xml.
  "terrain_name": "string",

  // Required. Grid dimensions and per-tile size in metres.
  "grid": {
    "rows": 3,
    "cols": 3,
    "tile_size": [8.0, 8.0]
  },

  // Optional. Connector strip between tiles. width=0 disables connectors.
  "border": {
    "width": 0.5,
    "match_mode": "min"  // "min" | "max" | "mean"
  },

  // Optional. "diverse" (per-tile colours), "uniform" (single colour from
  // terrain_style.xml), "custom" (per-type overrides in `palette`).
  "palette_preset": "diverse",

  // Optional, only consulted by "custom" or to override individual colours
  // in "diverse" mode. Keys are tile type names (or "connector").
  "palette": {
    "stairs": [0.3, 0.5, 0.85, 1.0]
  },

  // Optional. Bind a 2D texture to the uniform-mode material.
  "texture": {
    "file": "CONCRETE.png",            // relative to project root
    "name": "terrain_concrete",
    "repeat": [0.5, 0.5],
    "texuniform": true
  },

  // Explicit per-cell placements. Combine with `randomization` to fill the
  // rest of the grid.
  "tiles": [
    { "row": 0, "col": 0, "type": "flat", "params": { "height": 0.0 } }
  ],

  // Optional. Sampling spec for any cell not covered by `tiles`.
  "randomization": {
    "seed": 42,
    "weights": { "flat": 0.5, "stairs": 0.3, "rough": 0.2 },
    "param_ranges": {
      "stairs":  { "n_steps": [4, 10], "axis": ["x", "y"] },
      "rough":   { "vertical_relief": [0.3, 1.0] }
    }
  }
}
```

---

## CLI reference

The package installs as `myoassist-terrains`. Equivalent to
`python -m myoassist_terrains`.

```bash
# Build a terrain XML from a JSON config (and optionally activate it).
myoassist-terrains build path/to/config.json [--activate]

# Switch the active terrain pointer (rewrites the include in terrain_config.xml).
myoassist-terrains set-active <terrain_name>

# List all terrains in the current project's terrain library, marking the active one.
myoassist-terrains list

# Emit a <mujoco>-rooted wrapper that loads ONLY the terrain (no user model).
# Useful for visual QC.
myoassist-terrains preview <terrain_name>
```

The CLI discovers the project root by walking up from CWD looking for
`terrain_config.xml`. To override, set `MYOASSIST_TERRAINS_ROOT=/path/to/project`.

---

## Python API

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
| `myoassist_terrains.velocity_map.generate_velocity_map(...)`| Sample a 3D velocity field over a terrain (see [Velocity maps](#velocity-maps)). |
| `myoassist_terrains.velocity_arrows.add_velocity_overlay(...)`| Inject non-colliding velocity-arrow geoms into an existing scene. |

---

## Velocity maps

A **velocity map** is a sampled 3D vector field laid over a terrain: at points
across every tile it stores a direction (toward a goal, optionally with a
per-tile radial component) and a speed that is slowed by the local tile type,
surface grade, and roughness. It is used to author and visualize
target-velocity fields for locomotion tasks (the field rendered in the paper's
Fig. 3(b)) and as an input to velocity-tracking rewards downstream.

The subsystem is two modules:

- **`myoassist_terrains.velocity_map`** — builds the field from a
  `TerrainConfig` (no MuJoCo model needed).
- **`myoassist_terrains.velocity_arrows`** — turns a field into red→green arrow
  geoms injected into an MJCF scene for rendering.

### Building a field

```python
from pathlib import Path
from myoassist_terrains.config import load_config
from myoassist_terrains.velocity_map import generate_velocity_map

config  = load_config(Path("utils/configs/myoassist_base.json"))
samples = generate_velocity_map(
    config,
    start=(-10.0, -10.0, 0.0),
    goal=(10.0, 10.0, 0.0),
    samples_per_tile=8,
    mode="tile",          # "goal": every arrow points at the goal;
                          # "tile": add a per-tile radial component
)
# each sample is a VelocitySample: row, col, tile_type,
#   position=(x, y, z), velocity=(vx, vy, vz), speed
```

`generate_velocity_map(config, *, start, goal, samples_per_tile=10,
base_speed=1.0, height_offset=0.35, speed_scale=None, mode="goal",
smooth_speeds=True, tile_radial_mode="mixed", tile_speed_jitter=0.0,
tile_jitter_seed=0)` returns `list[VelocitySample]`. Key knobs:

| Parameter | Meaning |
|-----------|---------|
| `start`, `goal` | World `(x, y, z)`; horizontal direction points from each sample toward `goal`. |
| `samples_per_tile` | Grid density per tile (`n × n` samples). |
| `base_speed` | Speed on flat terrain before per-tile / grade scaling. |
| `speed_scale` | Override the per-tile-type multiplier (default `DEFAULT_SPEED_SCALE`, flat `1.0` → gap `0.25`). |
| `mode` | `"goal"` (straight to goal) or `"tile"` (blend in a radial component). |
| `tile_radial_mode` | For `mode="tile"`: `"inward"`, `"outward"`, or `"mixed"`. |
| `smooth_speeds` | Spatially smooth neighbouring sample speeds. |
| `tile_speed_jitter`, `tile_jitter_seed` | Deterministic per-tile speed variation in `[1-j, 1+j]`, so identical tile types still read distinctly. |
| `height_offset` | Lift samples above the surface (arrow placement). |

Two surface-height helpers back the field and are useful on their own:
`estimate_surface_height(tile, local_x, local_y, tile_size)` (per-tile-type
walkable height at a local coordinate) and `surface_height_at(config, tiles, x,
y)` (world-coordinate lookup across the resolved grid).

### Rendering arrows

`add_velocity_overlay(worldbody, asset, samples, *, emission=0.0,
color_bins=32)` appends a shaft + cone-head arrow per sample to an existing
scene's `<worldbody>`/`<asset>` (`xml.etree.ElementTree` elements). Arrows are
non-colliding (`contype/conaffinity=0`) and coloured red (slow) → green (fast)
across the observed speed range; `emission > 0` makes them self-illuminate so
they stay legible against the terrain. Call it after the terrain/model geoms
are in the scene so name-uniqueness checks pass.

### Ready-to-run renderers

Two scripts under `utils/render/` drive the above end to end (need the
`[render]` extra for `mediapy`):

```bash
# Terrain-only velocity overlay from a terrain config.
python utils/render/render_velocity_map.py \
    --terrain-config utils/configs/myoassist_base.json \
    --start -10 -10 0 --goal 10 10 0

# Terrain (+optional --arrows) with no musculoskeletal models; free or fixed
# camera. --emit-xml writes a viewer-ready scene instead of rendering.
python utils/render/render_terrain_check.py \
    --config utils/render/terrain5x5_velocity.json \
    --arrows --free --elevation -90 --distance 130
```

---

## Project layout for users

Project structure (e.g. a MyoAssist model repo) is expected to look like:

```
my_user_project/
├── terrain_config.xml        # active-terrain pointer; chains style + terrain
├── terrain_style.xml         # user-editable visuals (skybox, fog, lights)
├── terrain/                  # output of `myoassist-terrains build`
│   ├── flat_smoke_test.xml
│   ├── my_scene.xml
│   ├── my_scene_rough_r1c0.png   # hfield assets for rough tiles
│   └── ...
└── models/
    └── my_model.xml          # user model; includes terrain_config.xml
```

The user model includes the active-terrain pointer like:

```xml
<mujoco model="my_model">
  <!-- ... your model body, joints, etc ... -->
  <include file="../terrain_config.xml"/>
</mujoco>
```

`terrain_config.xml` in turn chains two includes:

```xml
<mujocoinclude>
  <include file="../terrain_style.xml"/>
  <include file="../terrain/my_scene.xml"/>
</mujocoinclude>
```

**Path resolution note.** MuJoCo resolves nested `<include>` paths relative to
the **top-level model file's directory**, not relative to the file containing
the `<include>`. The `../` prefix climbs out of the model directory before
descending into `terrain/`. The bundled templates assume the user model
lives one level below the project root.

See `utils/style/` for a working `terrain_config.xml` /
`terrain_style.xml` pair, including the `CONCRETE.png` texture used by the
default base config.

---

## Utilities and example configs

The `utils/` tree ships ready-to-use JSON configs, user-side style/asset
templates, and standalone helper scripts.

**Example configs** (`utils/configs/`):

| Path | What it is |
|------|------------|
| `flat_smoke_test.json`         | Minimum-viable 2x2 flat terrain. Use to verify a fresh install. |
| `m{2,3,4,4b,5}_*.json`         | Single-tile-type demos for development. |
| `rough_only.json`              | Rough-tile-only demo (hfield asset emission). |
| `myoassist_base.json`          | 3x3 base terrain (8 m tiles, all nine tile types, concrete texture). |
| `myoassist_tiled.json`         | 9x9 tiled version of the base; per-block rotations generated by `_make_tiled.py`. |
| `base.json`                    | 3x3 base block (5 m tiles) used by the tiled / velocity render pipeline. |
| `base_tiled3x3.json`           | 9x9 terrain (3x3 grid of `base` blocks) — the ensemble/velocity render terrain. |
| `base_tiled5x5.json`           | 15x15 terrain (`base` grown by 3 tile-rings); center matches `base_tiled3x3`. |

**Config helpers** (`utils/configs/`, `_`-prefixed, run directly):

| Path | What it is |
|------|------------|
| `_make_tiled.py`         | Derive a 9x9 tiled config from a 3x3 base with random per-block rotations. |
| `_make_tiled_rings.py`   | Grow the 9x9 tiled terrain outward by 3 rings → 15x15, preserving the center. |
| `_rebuild_myoassist.py`  | Rebuild `myoassist_base` + `myoassist_tiled` in one command (after editing the base JSON or style). |

**User-side style / asset templates** (`utils/style/`):

| Path | What it is |
|------|------------|
| `terrain_config.xml`        | Template active-terrain pointer. |
| `terrain_style.xml`         | Template style include (skybox, fog, lights, default `terrain_mat`). |
| `terrain/default.xml`       | Shipped default flat-ground terrain the pointer targets out of the box; `set-active default` restores it. |
| `CONCRETE.png`              | Sample concrete texture (1024x768). |

**Render tooling** (`utils/render/`, needs the `[render]` extra):

| Path | What it is |
|------|------------|
| `render_ensemble.py`        | Compose multiple models on a shared terrain and render from one or more cameras. |
| `render_terrain_check.py`   | Render terrain (+optional velocity arrows) with no models; free/fixed camera; can emit a viewer-ready XML. |
| `render_velocity_map.py`    | Render a terrain-only velocity-arrow overlay from a terrain config + start/goal. |
| `_build_ensemble_config.py` | Validate per-variant qpos lists and emit a ready-to-render ensemble JSON. |
| `_build_velocity_config.py` | Build the full ensemble render configs (`ensemble_velocity.json`, `ensemble_noarrows.json`, + smoke). |
| `camera_convert.py`         | Convert MuJoCo camera XML ↔ the `pos`/`xyaxes` JSON used in ensemble configs. |
| `ensemble_*.json`           | Generated ensemble render configs (model instances, per-instance qpos, cameras). |
| `terrain5x5_velocity.json`  | 5x5 terrain + velocity settings for `render_terrain_check.py`. |
| `terrain5x5_viewer.xml`     | Emitted viewer scene (open with `python -m mujoco.viewer --mjcf=...`). |
| `terrain_config.xml`, `terrain_style.xml` | Render-side style copies (tile `terrain_mat` rgba read from here). |
| `mesh/`                     | Device + anatomical meshes referenced by the ensemble render scenes. |

---

## Extending: adding a custom tile type

1. Drop a new module `src/myoassist_terrains/tiles/my_tile.py` with `DEFAULT_RGBA`,
   `DEFAULT_PARAMS`, `PARAM_RANGES`, and an `emit(spec, origin_xyz, name, *,
   tile_size, rgba=None, material=None, **params) -> TileEmitResult` function.
2. Wire it into `src/myoassist_terrains/tiles/__init__.py` so it appears in
   `REGISTRY` automatically.

Or, for plugin-style registration without forking:

```python
from myoassist_terrains import register_tile
from myoassist_terrains.tiles.base import TileEmitResult

def emit_my_tile(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params):
    # ... add geoms to spec.worldbody ...
    return TileEmitResult(base_height=0.0)

register_tile(
    "my_tile",
    emit_my_tile,
    default_params={"height": 0.0},
    param_ranges={"height": (0.0, 1.0)},
    default_rgba=(0.7, 0.7, 0.7, 1.0),
)
```

After registration, `"my_tile"` is a valid `"type"` value in any config.

---

## Development

```bash
pip install -e ".[dev]"
pytest                  # run the unit tests
pytest --cov            # with coverage
```

The test suite covers config validation, the tile registry, the composer
(layouts, palette resolution, sample terrain build), the velocity map
(sample coverage, goal-directed vectors, tile-mode direction), and a smoke
test that compiles a generated terrain through MuJoCo end-to-end.

---

## License

Apache 2.0. See [LICENSE](LICENSE).
