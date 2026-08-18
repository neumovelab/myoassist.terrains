# Velocity maps

A **velocity map** is a sampled 3D vector field laid over a terrain: at points
across every tile it stores a direction (toward a goal, optionally with a
per-tile radial component) and a speed that is slowed by the local tile type,
surface grade, and roughness. It is used to author and visualize
target-velocity fields for locomotion tasks and as an input to velocity-tracking
rewards downstream.

The subsystem is two modules:

- **`myoassist_terrains.velocity_map`** builds the field from a `TerrainConfig`,
  with no MuJoCo model needed. It requires the **grid** config form: a uniform
  terrain has no cells to sample over, and passing one is rejected with a message
  saying so. For point queries on a uniform surface use
  `myoassist_terrains.surface_height_at`.
- **`myoassist_terrains.velocity_arrows`** turns a field into red-to-green arrow
  geoms injected into an MJCF scene for rendering. The arrows are non-colliding.

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
| `speed_scale` | Override the per-tile-type multiplier. `DEFAULT_SPEED_SCALE` is derived from the registry, since each tile declares its own `SPEED_SCALE` (flat `1.0` down to gap `0.25`). A tile registered through `register_tile(..., speed_scale=...)` is covered automatically; one registered without it defaults to flat speed. |
| `mode` | `"goal"` (straight to goal) or `"tile"` (blend in a radial component). |
| `tile_radial_mode` | For `mode="tile"`: `"inward"`, `"outward"`, or `"mixed"`. |
| `smooth_speeds` | Spatially smooth neighboring sample speeds. |
| `tile_speed_jitter`, `tile_jitter_seed` | Deterministic per-tile speed variation in `[1-j, 1+j]`, so identical tile types still read distinctly. |
| `height_offset` | Lift samples above the surface (arrow placement). |

Surface heights come from the tiles themselves: `estimate_surface_height(tile,
local_x, local_y, tile_size)` dispatches to the tile's own `surface_height`, which
lives beside the `emit` that placed the geometry. For world-coordinate lookups
prefer `myoassist_terrains.surface_height_at(config, x, y)`, which also handles the
uniform config form and reports connector-strip heights.

`samples_per_tile=1` places its single sample at the tile center.

### Rendering arrows

`add_velocity_overlay(worldbody, asset, samples, *, emission=0.0,
color_bins=32)` appends a shaft + cone-head arrow per sample to an existing
scene's `<worldbody>`/`<asset>` (`xml.etree.ElementTree` elements). Arrows are
non-colliding (`contype/conaffinity=0`) and colored red (slow) -> green (fast)
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
