# Configuration schema

Developer reference. The narrative version, with examples and figures, is on the
[MyoAssist site](https://neumovelab.github.io/myoassist/modeling/terrains/configuration).

There are two config forms. A top-level `"terrain"` string selects the **uniform**
form (one continuous surface); anything else is the **grid** form (a tiled grid).
The dispatch is unambiguous because the grid form never carries that key.

Unknown top-level keys are rejected in both forms. A key prefixed with `_` is
allowed through as a comment. This matters more than it sounds: a config is an
experiment description, and `{"terrain": "slope", "dge": 8}` used to build flat
ground and report success.

---

## Uniform form

One plane or one heightfield. `flat` and `slope` emit a `mjGEOM_PLANE`; `random`
and `sinusoidal` emit a single heightfield with a smooth safe zone flattened around
the origin so a model does not spawn on a bump.

```jsonc
{
  "terrain": "sinusoidal",     // required: "flat" | "slope" | "random" | "sinusoidal"
  "terrain_name": "waves",
  "amplitude": 0.08,
  "period": 1.5,
  "extent": 20.0,
  "resolution": 256,
  "safe_zone_radius": 3.0
}
```

| Key | Default | Applies to | Description |
|-----|---------|------------|-------------|
| `terrain` | required | all | `"flat"`, `"slope"`, `"random"` or `"sinusoidal"`. |
| `terrain_name` | `"uniform_<terrain>"` | all | Output name; must be a bare file name, since it becomes `terrain/<terrain_name>.xml`. |
| `deg` | `0.0` | `slope` | Grade in degrees, `-90 < deg < 90`. Positive rises in `+x`, the walking direction. |
| `amplitude` | `0.1` | `random`, `sinusoidal` | Surface relief in meters. Must be `> 0`. |
| `period` | `1.0` | `sinusoidal` | Wavelength along `+x` in meters. Must be `> 0`. |
| `seed` | `0` | `random` | RNG seed. |
| `extent` | `20.0` | `random`, `sinusoidal` | Full side length of the surface in meters. Must be `> 0`. |
| `resolution` | `256` | `random`, `sinusoidal` | Heightfield grid resolution (`nrow == ncol`). Must be `>= 8`. |
| `safe_zone_radius` | `3.0` | `random`, `sinusoidal` | Radius in meters over which the surface is flattened toward 0 around the origin. `0` disables it. |
| `base_depth` | `1.0` | `random`, `sinusoidal` | Solid heightfield thickness below the surface in meters. Must be `> 0`. |
| `palette_preset` | `"uniform"` | all | `"diverse"`, `"uniform"` or `"custom"`. |
| `palette` | `{}` | all | Surface rgba under the key `"uniform"`, `"terrain"`, or the terrain type name. |
| `texture` | none | all | A texture block, as in the grid form below. |

`random` is white noise at cell scale: at the default `resolution` over the default
`extent` a cell is about 8 cm, so neighboring samples differ by up to `amplitude`.
Raise `extent` or lower `resolution` for longer-wavelength relief.

---

## Grid form

```jsonc
{
  // Required. The output XML is written as terrain/<terrain_name>.xml, so this
  // must be a bare file name (no separators, no "..").
  "terrain_name": "string",

  // Required. Grid dimensions and per-tile size in meters. The grid is centered on
  // the world origin; cell (row=0, col=0) is the most negative (x, y) corner, rows
  // increase in +y and cols in +x.
  "grid": {
    "rows": 3,
    "cols": 3,
    "tile_size": [8.0, 8.0]
  },

  // Optional. Connector strip between tiles. width = 0 disables connectors.
  // The strip's top face is match_mode over the cells it joins.
  "border": {
    "width": 0.5,
    "match_mode": "min"  // "min" | "max" | "mean"
  },

  // Optional. "diverse" gives each tile type its default color, with optional
  // per-type overrides in `palette`. "custom" is the same but REQUIRES an entry
  // for every placed type, so a final-render config checks itself. "uniform"
  // paints every tile one color and is the only preset a `texture` applies to.
  "palette_preset": "diverse",

  // Optional. Keys are tile type names, or "connector". Under palette_preset
  // "uniform", use the single key "uniform" instead; a per-type entry there is
  // rejected rather than silently discarded.
  "palette": {
    "stairs": [0.3, 0.5, 0.85, 1.0]
  },

  // Optional, palette_preset "uniform" only. `file` is resolved relative to the
  // project root and rewritten to a portable path in the emitted XML.
  "texture": {
    "file": "CONCRETE.png",
    "name": "terrain_concrete",
    "repeat": [0.5, 0.5],
    "texuniform": true
  },

  // Explicit per-cell placements. One tile per cell: a duplicate (row, col) is
  // rejected. Combine with `randomization` to fill the rest of the grid.
  "tiles": [
    { "row": 0, "col": 0, "type": "flat", "params": { "height": 0.0 } }
  ],

  // Optional. Sampling spec for any cell not covered by `tiles`. At least one of
  // `tiles` or `randomization` is required.
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

See [the tile catalog](tiles.md) for every tile `type` and its `params`.

### `randomization.param_ranges`

Each entry is either `[lo, hi]` for a numeric range (int when the parameter's
default is an int, float otherwise; `[v, v]` fixes it at `v`) or a list of
categorical choices. Two things are rejected rather than silently mishandled:

- **Reversed numeric bounds.** `[hi, lo]` used to work for floats, because numpy
  quietly samples `[hi, lo)`, while raising for ints.
- **List-valued parameters** such as `size_range`. A `[lo, hi]` spec would be read
  as a range and replace the list with one number, failing inside the tile. Set
  those directly in the tile's `params`.
