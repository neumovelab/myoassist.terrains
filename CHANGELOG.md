# Changelog

Rationale lives here rather than in commit messages. Versions follow
[semantic versioning](https://semver.org/); a release is cut by bumping `version`
in `pyproject.toml`, adding the entry below, then pushing a `vX.Y.Z` tag, which is
what triggers publication.

## Unreleased

## 1.0.0

First stable release, cut in step with the MyoAssist 1.0.0 line. No functional changes since
0.2.0; the public API (`build_terrain`, the config schema, the surface queries, and the tile
registry) is considered stable.

## 0.2.0

Remediation pass following a full framework review. Each entry below states what
changed and, where it matters, the measurement behind it.

### Changed geometry

These alter the terrain a given config produces. Existing built XML and rendered
figures will differ.

- **`stairs` reserves a landing.** When `step_width` is left unset it is now
  `(long - peak) / (2n + 2)` instead of `(long - peak) / (2n)`, leaving exactly one
  tread of flat margin at each end, and the `inverted` form emits its base as a
  four-sided frame. Previously the staircase spanned the tile edge to edge, so the
  first riser sat flush with the boundary and every stairs-to-connector seam was a
  `step_height` wall. Measured: the tile perimeter moves from `+0.150` to `0.000`.
  Treads shrink 14.3% at `n_steps=6` (38.3 cm to 32.9 cm on a 5 m tile); peak
  height and plateau width are unchanged. Affects the four shipped configs that
  use auto-fill; `m2_demo` and `m3_demo` pass an explicit `step_width` and are
  untouched.
- **`rough` places its heightfield correctly.** MuJoCo renormalizes hfield data to
  its own range before scaling, which the geom origin now inverts. The default
  `relief_mode="centered"` had its perimeter sitting 3.6% of `vertical_relief`
  above `base_height` (+32.8 mm at relief 0.9); it is now within 0.2 mm. A pure
  vertical translation: shape and total relief are unchanged, and `"up"`/`"down"`
  were already exact. `vertical_relief` continues to mean peak-to-trough
  excursion.
- **Scatter tiles stay inside their cell.** `boulders` and `discrete_obstacles`
  inset placement by `edge_margin` *plus* the sampled size, rather than insetting
  only the object centre. A default-configuration boulder could previously
  overhang its cell into the connector strip by up to 9 cm, and up to 39 cm at the
  `edge_margin` end of its randomization range. Measured over 200 seeds: 173/200
  seeds overhanging becomes 0/200. Object positions move for a given seed.

### Changed asset names

- **Heightmap filenames are content-addressed** (`<terrain>_<tile>_<digest>.png`).
  MuJoCo caches decoded file assets by path within a process, so a name derived
  only from the terrain and tile silently served the first build's heightfield to
  every later build under the same name -- verified by two different seeds
  producing identical compiled elevation. `docs/project-layout.md`'s example
  filename changes accordingly.
- `myoassist-terrains build` now removes superseded heightmaps for the terrain it
  is building. `build_terrain(..., prune_assets=True)` opts in; it is off by
  default because a shared asset directory may hold files another consumer still
  references.

### Added

- **`surface_height_at(config, x, y)` and `max_surface_height_in(config, x, y, r)`.**
  Public queries for the walkable surface height, so a consumer placing something
  on the terrain can ask the package that owns the geometry instead of
  collision-probing a compiled model. Handles both config forms and reports
  connector-strip heights. `TerrainSurface` caches the per-config setup for
  repeated queries (2.4 us each, against 0.3 ms to build).
- **`register_tile(..., surface_height=..., speed_scale=..., param_docs=...)`.**
  A custom tile can now describe its own surface and speed. Previously a
  registered tile built fine and then failed inside the velocity map, which had no
  entry for it.
- `--root` on every subcommand, so `build`/`list`/`preview` work from outside a
  project tree, and `--version`.
- Python 3.13 is tested and declared.

### Fixed

- **`python -m myoassist_terrains` returns a non-zero exit code on failure.** It
  reported success for every error, so a script checking the return code walked
  past a missing config. `docs/cli.md` called the module and console-script
  invocations equivalent; now they are.
- **The velocity map's height model agreed with nothing.** It kept a second,
  hand-derived model of each tile's surface, wrong for four of the nine types: the
  `stairs` level was off by one step in one direction with auto-fill and the other
  with an explicit `step_width`, the `rough` heightmap was sampled y-mirrored, the
  `pyramid_stairs` flat outer margin was promoted a level by `int()` truncating
  toward zero, and the scatter tiles reported base height rather than their
  objects. Each tile now owns a `surface_height` beside its `emit`, and
  `tests/test_surface_contract.py` ray-casts the compiled model to hold them
  together.
- **Heightfields are interpolated the way MuJoCo builds them** (main-diagonal
  triangles, not bilinearly). Bilinear was off by up to 30 mm between nodes, which
  fed directly into how deep a model was seated.
- `myoassist-terrains preview` produces a lit, loadable scene. It chained no style
  file despite a docstring claiming otherwise, so it compiled with zero lights and
  zero textures and rendered unlit geometry on black. It also declares a usable
  offscreen framebuffer instead of inheriting MuJoCo's 640x480 default.
- The `terrain_style.xml` colour pickup for `palette_preset="uniform"` is gone.
  It only fired when `output_dir` was passed *and* a style file happened to sit one
  level above it, so the same config rendered different colours depending on how it
  was built, and it never fired through myoassist's compose at all. Set the colour
  with `palette: {"uniform": [r, g, b, a]}`; the five shipped uniform-preset configs
  now carry the colour they previously picked up, so their appearance is unchanged.
- `surface_height_at` reports the connector strip's negotiated `match_mode` height
  instead of `0.0`.
- A single velocity-map sample per tile sits at the tile centre. `samples_per_tile=1`
  placed its one sample at 32% of the tile from the centre.

### Now rejected (previously silent, or failed deep)

A terrain config describes an experiment, so a typo that quietly changes the ground
is worse than a crash.

- Unknown top-level keys in either config form. `{"terrain": "slope", "dge": 8}`
  used to build flat ground and pass validation. Keys prefixed with `_` are still
  allowed as comments.
- Unknown tile `params`, reported with the tile type and cell instead of a bare
  `TypeError` naming `emit`.
- Two tiles in one cell, which used to overlap silently or collide on a MuJoCo geom
  name depending on whether the types matched.
- `pyramid_stairs` with `inverted=True` and `outer_margin=0`, or `outer_margin`
  at least half the tile: both reached MuJoCo as `size 1 must be positive in geom`.
- A `texture` block outside `palette_preset="uniform"`, which was discarded along
  with any typo in its path.
- Per-type `palette` entries under `palette_preset="uniform"`, which were computed
  and then thrown away. A single `"uniform"` or `"terrain"` entry is honoured.
- `palette_preset="custom"` without an entry for every placed tile type. `custom`
  was byte-identical to `diverse`, so it was a value that only looked meaningful.
- Randomizing a list-valued tile parameter such as `size_range`, which used to
  replace the list with a single number and fail inside the tile.
- A reversed float range in `param_ranges`. numpy silently samples `[hi, lo)`, so
  reversed bounds worked for floats while raising for ints.
- A `terrain_name` that is not a bare filename, which wrote the generated XML
  outside the terrain library. Both `/` and `\` are rejected on every platform:
  `pathlib` only treats a backslash as a separator on Windows, so leaning on it would
  make the same config an error on Windows and legal on Linux.

### Internal

- Input validation in `velocity_map` and `velocity_arrows` raises `ValueError`
  instead of asserting, so `python -O` no longer strips it. Genuine internal
  invariants remain assertions and are marked as such.
- `surface_height_at` resolves tiles and the cell layout once per config rather
  than per call, which was about 60% of a 15x15 velocity render's runtime; that
  render drops from 7.6 s to 2.3 s.
- Only tile types a config can place get a palette material, rather than every
  type in the registry.
- Removed `TileEmitResult.boundary_heights` and the unused `cell_results`,
  `geom_name`, `uniform_rgba` and `asset_path_prefix` parameters, none of which was
  ever read. `asset_path_prefix` in particular looked like a per-tile control over
  the emitted asset path and did nothing.
- Removed `uv.lock`: nothing consumed it, and CI installs with pip.

### Testing

- Test count goes from 84 to 182. `cli.py` and `paths.py` go from no coverage to
  full; `velocity_arrows.py` from none to covered. Overall 84%.
- `tests/test_surface_contract.py` ray-casts every tile and every `inverted`
  variant, asserting the flat-at-base contract and that each height model matches
  its emitted geometry. `gap` is the one documented exception, since its trench
  mouth reaches the tile edge by design.
- CI adds a Windows leg (the package carries three Windows-only path workarounds
  that were never exercised on Windows) and Python 3.13, reports coverage, and
  gates publication on the test workflow rather than allowing a manual dispatch to
  publish an untested tree.

## 0.1.0

First release: package layout, JSON config schema, nine tile types, the
`myoassist-terrains` CLI, example configs, style templates and render utilities.
