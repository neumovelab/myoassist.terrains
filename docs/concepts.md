# Concepts

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
