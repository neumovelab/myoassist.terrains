# `myoassist-web` changelist

Scoped, not applied. Per the session's write scope, `myoassist-web` was left alone
because it has uncommitted work on `compose-1.0-docs`.

The website is canonical for user-facing terrain prose; `myoassist.terrains/docs/`
is now explicitly the developer reference and links out to the site. So the items
below are the user-facing half of the same corrections, plus what the code changes
made newly true or newly false.

## 1. Factual corrections (the same errors, in the website copy)

| File | Line | Now says | Should say |
|---|---|---|---|
| `modeling/terrains/tile-types.md` | 11 | "All angles are in radians unless noted." | Angles are in **degrees** where a parameter name says so (`angle_deg`). No tile parameter is in radians. |
| `modeling/terrains/tile-types.md` | 136, 180 | `density` is an "Approximate fraction of tile area covered" | Objects **per square meter**; the count is `round(density * tile_area)`. |
| `modeling/terrains/tile-types.md` | 174 | "Randomly placed half-sphere boulders" | Ellipsoids with independently sampled per-axis radii, half-buried in the base slab. |
| `modeling/terrains/tile-types.md` | 181 | `size_range` is "Min and max boulder **diameter**" | Min and max **radius**. The old wording understated boulder size by 2x, which is what hid the overhang defect. |
| `modeling/terrains/tile-types.md` | 111 | `vertical_relief` is the "Total `[min, max]` heightmap range, scaled by `hfield_size_z`" | Peak-to-trough excursion of the surface in meters. (`vertical_relief` *is* `size[2]`, so the old wording was circular.) |
| `modeling/terrains/tile-types.md` | 118 | `edge_taper_frac` tapers "heights to 0 at the tile edge" | The band over which the surface returns to `base_height`. Only `relief_mode="up"` tapers the heightmap to 0; the default `"centered"` tapers to 0.5. |
| `modeling/terrains/configuration.md` | 13-14 | "Only `terrain_name` and `grid` are required." | Also required: `tiles`, `randomization`, or both. Verified: a config with only those two raises. This one is website-only; the local docs never claimed it. |

The local tile tables are now **generated** from the registry by
`utils/docs/_gen_tile_catalog.py`, with a test that fails if they go stale. The
website tables are wrapped in per-tile figure `<div>`s, so they cannot be dropped in
wholesale; the descriptions can be copied from the generated block, or the generator
taught a website mode.

## 2. Made true by the code, so the wording can stay

- `modeling/terrains/index.md:49-53` and `tile-types.md:12-14`: the flat-at-base
  boundary contract. It was false for `stairs` (auto `step_width` put the first riser
  flush with the tile edge) and `rough` (heightfield placement ignored MuJoCo's
  renormalization). Both are fixed, so the claim now holds. **Add the one exception:**
  `gap` opens its perimeter by design, since its trench mouth reaches the tile edge.

## 3. Made false by the code, so the wording must change

- `modeling/terrains/index.md:62`: "Every tile shares the colour of `terrain_mat`
  from `terrain_style.xml`". That read is **removed**. It only fired when
  `output_dir` was passed and a style file happened to sit one level above it, so the
  same config produced different colours depending on how it was built, and it never
  fired at all through `compose`, which is how the site's audience reaches terrain.
  Replace with: every tile shares one colour, set by
  `palette: {"uniform": [r, g, b, a]}`.
- `modeling/terrains/index.md:63`: `custom` described as "Like `diverse`, but with
  per-type rgba overrides". It was byte-identical to `diverse`. It now **requires** an
  entry for every placed tile type, so a final-render config checks itself.
- `modeling/terrains/tile-types.md`, `stairs.step_width`: auto-fill now reserves one
  tread of flat landing at each end rather than spanning the tile edge to edge.
- Anywhere the asset filename appears: heightmap names now carry a content digest
  (`<terrain>_<tile>_<digest>.png`).

## 4. New content the site does not have

**A uniform-terrain page.** `getting-started/defining-an-environment.md:81-86` has a
four-row table covering `flat`, `slope`+`deg`, `random`+`amplitude` and
`sinusoidal`+`amplitude`/`period`. Nothing anywhere documents `seed`, `extent`,
`resolution`, `safe_zone_radius`, `base_depth`, `terrain_name`, `palette` or
`texture` on that form. Given RL and CO runs are authored with inline uniform dicts,
`resolution`, `extent` and `safe_zone_radius` are the ones users most need. The
field table in `docs/configuration.md` can be lifted directly.

**Surface queries.** `surface_height_at(config, x, y)` and
`max_surface_height_in(config, x, y, radius)` are new public API and are how a
consumer should ask where the ground is. Worth a short section, because the
alternative people reach for (collision-probing a compiled model) is what produced
models buried metres into their terrain.

**Configs are now validated.** A page or a callout listing what is rejected would
save users a round trip: unknown keys, duplicate cells, a `texture` outside uniform
mode, per-type palette entries under uniform, list-valued randomization targets,
reversed numeric ranges, and a `terrain_name` that is not a bare filename. The
motivating case is worth stating plainly: `{"terrain": "slope", "dge": 8}` used to
build flat ground and report success.

## 5. Figures to regenerate

- `assets/terrains/stairs.png`: the tile now has a visible flat landing at each end
  and slightly steeper treads (38.3 cm to 32.9 cm on a 5 m tile at `n_steps=6`).
- `assets/terrains/boulders.png` and `discrete_obstacles.png`: object positions moved,
  because placement is now inset by the sampled size rather than only the centre.
- `assets/terrains/rough.png`: shifted down by about 3.6% of `vertical_relief`. Likely
  imperceptible; regenerate for consistency rather than visibility.
- Wide shots (`base_tiled_diverse.png`, the velocity-map figure): the stairs change is
  indistinguishable at that framing, so these can stay unless regenerating anyway.

## 6. Third copy

`myoassist/docs/reinforcement-learning/03_terrain-types.md` overlaps both and is
currently the only place inside the `myoassist` repo that tabulates the uniform form.
Recommend retiring it in favour of the website page once item 4 lands, so terrain
schema lives in one user-facing place.
