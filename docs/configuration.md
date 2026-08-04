# Configuration schema

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
