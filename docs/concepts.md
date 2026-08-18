# Concepts

Developer reference for the terrain model. The narrative version, with figures, is
on the [MyoAssist site](https://neumovelab.github.io/myoassist/modeling/terrains/).

### Two config forms

A top-level `"terrain"` string selects a **uniform** terrain: one continuous
surface, either a plane (`flat`, `slope`) or a single heightfield (`random`,
`sinusoidal`). Anything else is the **grid** form: a tiled grid of finite cells.
Both are accepted by `build_terrain`. See [Configuration](configuration.md).

### Grid

A `rows x cols` grid of square or rectangular **tiles** with a configurable
`tile_size = (width_x, length_y)`. The grid is centered on the world origin. Cell
`(row=0, col=0)` is the most negative `(x, y)` corner; rows increase in `+y` and
columns in `+x`.

### Tiles

Each cell holds one **tile type** from the registry. A tile module supplies its
`DEFAULT_PARAMS`, `PARAM_RANGES`, `PARAM_DOCS`, an `emit(...)` that adds geoms to a
MuJoCo `MjSpec`, and a `surface_height(...)` that reports the walkable surface
height at a tile-local coordinate. Those last two are two views of the same
geometry and are required to agree.

### Connectors

A flat connector strip of `border.width` meters separates the cells; set the width
to `0` to make tiles touch. Edge connectors and corner pieces are generated
automatically, and their top face is matched to the neighboring tile heights
through `border.match_mode = "min" | "max" | "mean"`. Connectors span down to
`BASELINE_Z = -2.0`, so a height difference reads as a clean step riser rather than
a floating shelf. `surface_height_at` reports the negotiated height over a strip.

### Boundary contract

Every tile presents a flat top at its declared `base_height` around its whole
perimeter, so a connector joins it cleanly whatever happens in the middle of the
tile. **`gap` is the one exception**: its trench mouth reaches the tile edge, which
is the point of the tile.

The contract is measured, not assumed. `tests/test_surface_contract.py` ray-casts
the compiled model at 36 points around every tile, and every `inverted` variant.
Two tiles used to break it silently: `stairs` with an auto-computed `step_width`
put its first riser flush with the edge, and `rough` placed its heightfield without
accounting for MuJoCo's renormalization.

### Palette

Three modes, set by `palette_preset`:

| Mode | Behavior |
|------|-----------|
| `diverse` | Each tile type renders in its own default color. Per-type overrides in `palette` are honored. Easy to read while tuning a config. |
| `custom` | Like `diverse`, but **requires** a `palette` entry for every placed tile type. A final-render config then checks itself instead of quietly falling back to defaults. |
| `uniform` | Every tile shares one color, from `palette: {"uniform": [r, g, b, a]}`, or a neutral gray default. The only preset a `texture` applies to; a per-type `palette` entry is rejected here rather than discarded. |

### Texture

A single 2D texture can be bound to the uniform material through a `texture` block,
for a concrete, asphalt or dirt finish on final-render terrains. It applies only
under `palette_preset="uniform"`, and supplying one elsewhere is an error rather
than a silent no-op.

### Randomization

Cells not covered by an explicit `tiles` entry are filled by sampling a tile type
from `randomization.weights`. Each sampled tile's parameters are drawn from
`randomization.param_ranges[type]` or the tile's built-in `PARAM_RANGES`. Explicit
`tiles` and `randomization` coexist: explicit placements win and the rest is
sampled.

### Surface queries

`surface_height_at(config, x, y)` and `max_surface_height_in(config, x, y, radius)`
report the walkable surface height from the config alone, with no compiled model.
They exist so a consumer placing something on the terrain can ask the package that
owns the geometry rather than collision-probing for it. Use the footprint query for
anything with extent: a point query between two stepping stones reports the base
slab, which is not where a foot would rest.
