# Framework review remediation

Fixes everything found in a full-repository review. Findings and measurements are in
`FRAMEWORK_REVIEW.md`; every decision, its rationale, the alternatives rejected and
the six things that turned out differently from the plan are in
`REVIEW_DECISIONS.md`. Behaviour changes are in `CHANGELOG.md`.

Paired with one commit on `myoassist` (`ctrl_optim-testing`): the seating fix needs
both sides.

## Why the diff is shaped the way it is

Two structural changes account for most of it, and each closes a *class* of defect
rather than an instance.

**Each tile now owns its own `surface_height`, beside the `emit` that places the
geometry.** The velocity map used to keep a second, hand-derived model of every
tile's surface, and it was wrong for four of the nine types. `tests/test_surface_contract.py`
ray-casts the compiled model and holds the two together, so a change to one that does
not match the other fails there instead of silently misplacing arrows or seating a
model inside the ground.

**The tile catalog in `docs/tiles.md` is generated from the registry.** Four of the
documentation findings were the same problem: a hand-maintained table drifting from
the code. `density` was documented as an area fraction when it is a count per square
meter; `boulders` as half-spheres taking a diameter range when they are ellipsoids
taking radii, which is what hid a real overhang defect.

## Verified

| | |
|---|---|
| Tests | 84 -> 183 (1 skipped: `gap`'s documented perimeter exception) |
| Coverage | 84%; `cli.py` and `paths.py` 0% -> 100%, `velocity_arrows.py` 0% -> covered |
| `ruff check` + `format --check` | clean, with `I` and `ARG` newly enabled |
| mujoco 3.3.3 / 3.4.0 / 3.11.0 | 183 passed on each |
| Python 3.12 / 3.13 | 183 passed on each |
| Shipped configs | all 13 build, compile, and keep their exact colours |
| Documented render commands | both run from a clean clone |
| Seating through `myoassist` compose, 11 terrain types | all settle; root moves <= 2 mm in the first 20 ms |
| Compose cache, tiled terrain across 3 processes | loads on a warm cache (previously a hard failure) |

## Behaviour changes worth knowing before merging

Three change emitted geometry, so existing built XML and rendered figures differ.
Details and measurements in `CHANGELOG.md`.

- **`stairs` reserves a landing.** Auto-fill is now `(long - peak)/(2n + 2)`, leaving
  one tread of flat margin at each end. It previously spanned the tile edge to edge,
  so the first riser sat flush with the boundary and every stairs-to-connector seam
  was a `step_height` wall. Perimeter measured at `+0.150` before, `0.000` after.
  Treads shrink 14.3% at `n_steps=6`; peak height and plateau width unchanged.
- **`rough` places its heightfield correctly.** MuJoCo renormalizes hfield data
  before scaling, which the geom origin now inverts. The default `relief_mode`
  had its perimeter 3.6% of `vertical_relief` high (+32.8 mm at relief 0.9); now
  within 0.2 mm. A pure vertical translation, so shape and relief are unchanged.
- **Scatter tiles stay inside their cell.** Placement is inset by `edge_margin` plus
  the sampled size. Over 200 seeds, boulders overhanging their cell goes from
  173/200 to 0/200 at the randomization extreme. Object positions move for a seed.
- **Heightmap filenames are content-addressed.** MuJoCo caches decoded assets by
  path within a process, so a name derived only from the terrain and tile served the
  first build's heightfield to every later build under that name.

## New public API

- `surface_height_at(config, x, y)` and `max_surface_height_in(config, x, y, radius)`.
  A consumer placing something on the terrain can ask the package that owns the
  geometry instead of collision-probing a compiled model, which is what produced
  models buried 1.6-2.6 m into their terrain.
- `register_tile(..., surface_height=..., speed_scale=..., param_docs=...)`, so a
  custom tile describes its own surface and speed rather than failing inside the
  velocity map.
- `--root` on every subcommand, and `--version`.

## Now rejected, previously silent

A terrain config describes an experiment, so a typo that quietly changes the ground
is worse than a crash. `{"terrain": "slope", "dge": 8}` used to build flat ground and
pass validation. Also rejected: duplicate cells, degenerate `pyramid_stairs` margins,
a `texture` or per-type `palette` that would be discarded, list-valued randomization
targets, reversed float ranges, and a `terrain_name` that escapes the terrain library.

## Not in this PR

- **Figures are not regenerated.** `WEBSITE_CHANGELIST.md` lists which ones the
  geometry changes affect, with an assessment of whether the difference is visible.
- **`myoassist-web`** is scoped in `WEBSITE_CHANGELIST.md`, not changed here.
- **`flat_smoke_test.json`** spawns the model at a 4-way corner across a 0.5 m step,
  where no placement both touches the ground and avoids interpenetration. Seating
  correctly lifts to clear it. That is a poor spawn point rather than a defect, so
  the config is unchanged.
