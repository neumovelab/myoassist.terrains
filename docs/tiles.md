# Tile catalog

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
