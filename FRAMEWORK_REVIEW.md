# Framework review — `myoassist.terrains` @ `984a06f` (main)

Full-repository review: `src/` (3.3k LOC), `tests/` (0.9k), `docs/` (655 lines),
`utils/` (1.5k), both CI workflows, packaging, and the cross-repo consumption
surface. Report only; no source files were changed.

## What was run

| Check | Result |
|---|---|
| `pytest -q` on mujoco **3.4.0** (py3.12) | 84 passed |
| `pytest -q` on mujoco **3.3.3** (py3.12) | 84 passed |
| `ruff check .` / `ruff format --check .` (pinned 0.15.20) | clean / 39 files formatted |
| CLI end to end in a scratch project (`build --activate`, `set-active`, `list`, `preview`) | works, grid **and** uniform forms |
| README quickstart, verbatim | works; preview XML loads and renders |
| `render_velocity_map.py` + `render_terrain_check.py` (both documented commands) | both succeed |
| Ray-cast surface measurement vs. every claim about tile geometry | see Major findings |
| Overhang scan: 200 seeds × 3 scatter tiles × 2 param sets | see V3 |
| All 13 shipped configs built + compiled + boundary-scanned | all build; none currently trips V3 |

No blockers. The package works, the tests pass, the CLI and the documented render
commands run, and the cross-repo public surface is clean (the downstream consumer
imports only `build_terrain`, `load_config`, `config_from_dict` — no private
symbols). The findings below are real defects and gaps, not build breakage.

The most consequential cluster is that **nothing in the test suite measures the
emitted surface**, so two classes of geometry error survive: the velocity map's
height model disagrees with the terrain it describes (M1, M2, M6), and the
documented flat-at-base boundary contract is violated by the default
configuration of two tiles (M4, M5).

---

## Major

### M1. `_stairs_height` is wrong at nearly every point, in both directions
`src/myoassist_terrains/velocity_map.py:365-382`

Measured against ray-cast truth on an 8 m tile, `step_height=0.15`:

| config | result |
|---|---|
| defaults (auto `step_width`) | under-reports by exactly 0.150 m at **16 of 17** probes |
| explicit `step_width=0.5` | over-reports by exactly 0.150 m at **12 of 17** probes |

Two independent causes:

1. **Missing `+1`.** Step *i* spans `[i·sw, (i+1)·sw)` with its top at
   `base + (i+1)·step_height` (`stairs.py:174-178`), but line 378 computes
   `level = int(dist_from_edge / step_width)`. `_pyramid_height:395` has the
   `+ 1`; `_stairs_height` does not.
2. **Ignores the flat base margin.** `dist_from_edge` (line 377) is measured from
   the *tile* edge, but when `stair_span < long_total` the staircase starts
   `(long_total - stair_span)/2` inside the tile. Nothing subtracts that offset,
   so the whole profile shifts by `margin/step_width` steps.

Impact: arrow z placement over every stairs tile, plus `grade` and `roughness`
(and therefore the speed) in `_direction_and_grade` / `_local_surface_roughness`.

### M2. `_rough_height` samples the rough heightmap y-mirrored
`src/myoassist_terrains/velocity_map.py:457-478`

MuJoCo reads PNG row 0 as the hfield's **last** row (image top = +y).
`_bilinear_heightmap_sample` maps `local_y = -half` to row 0. Verified by
correlating the compiled `hfield_data` against the written PNG:

```
corr(hfield, png as-is)     = -0.32766
corr(hfield, png y-flipped) = +1.00000
```

Consequence on a 0.9 m relief tile: mean |error| 0.122 m as-is vs. 0.050 m
flipped (max 0.490 m vs. 0.105 m). The velocity field over rough tiles is
mirrored relative to the terrain it sits on.

The 0.050 m residual after flipping is M5.

### M3. `python -m myoassist_terrains` throws away the exit code
`src/myoassist_terrains/__main__.py:5`

`main()` is called without `sys.exit(...)`. `cli.py:206-207` and the setuptools
console-script wrapper both exit properly, so only the `-m` path is affected:

```
build (missing config):     console script -> 2    python -m -> 0
set-active (missing name):  console script -> 2    python -m -> 0
```

`docs/cli.md:3-4` states the two invocations are "Equivalent". There is an
in-repo victim: `utils/configs/_rebuild_myoassist.py:31,38` shells out through
`python -m myoassist_terrains build` and checks `returncode`, so the rebuild
helper silently proceeds past a failed build.

### M4. The default `stairs` tile violates the documented boundary contract
`src/myoassist_terrains/tiles/stairs.py:99-105`; contract stated at
`docs/concepts.md:25-29`, `composer.py:24-25`, `stairs.py:10`

When `step_width` is `None` (the default, and what randomization deliberately
leaves unset — `stairs.py:46-48`), auto-fill sets
`step_width = (long_total - peak_width)/(2·n_steps)`, so
`stair_span == long_total` exactly and step 0's riser sits flush with the tile
edge. Measured perimeter on the long axis: **+0.150 m**, not `base_height`.
With an explicit `step_width` the contract holds (measured 0.000).

The seam this produces — stairs beside a flat neighbour, `match_mode="min"`:

```
      y        z   geom
  -0.24  +0.0000   connector_ns_r0c0
  +0.00  +0.0000   connector_ns_r0c0
  +0.24  +0.0000   connector_ns_r0c0
  +0.30  +0.1500   stairs_r1c0_step_up_0     <-- one riser above the connector
```

The connector is placed at `base_height` because `TileEmitResult.base_height`
reports the *declared* base (`stairs.py:191`), which is no longer what the tile
presents at its edge. So every stairs boundary is a `step_height` wall.

For contrast, `slope` honours the contract exactly (measured 0.0002 m on all four
edges) and `slope.py:10-15` documents its cross-axis compromise honestly.

Related: the `inverted` variants of `stairs`, `slope` and `pyramid_stairs` omit
the base slab across the active region entirely (`stairs.py:142-151`,
`slope.py:143-152`, `pyramid_stairs.py:116-148`), leaving the perimeter open;
`default_categorical` selects `inverted` 50% of the time under randomization
(`tiles/__init__.py:43,51,59`). `docs/concepts.md`'s contract is stated without
exceptions.

### M5. The `rough` tile does not compensate for MuJoCo's hfield renormalization
`src/myoassist_terrains/tiles/rough.py:141-177`

MuJoCo renormalizes hfield data to its own [min, max] before scaling by
`size[2]`. `composer._emit_uniform_hfield` handles this explicitly
(`composer.py:450-466`, with a comment explaining it); the `rough` tile does
not. In the default `relief_mode="centered"` the taper's mid-value 0.5 is
therefore no longer the mid-value after renormalization:

| `relief_mode` | png min | png max | actual relief | perimeter z |
|---|---|---|---|---|
| `centered` (default) | 0.0118 | 0.9255 | 0.9000 | **+0.0328** |
| `up` | 0.0000 | 0.8784 | 0.9000 | +0.0000 |
| `down` | 0.1216 | 1.0000 | 0.9000 | +0.0000 |

The relief is preserved, but the perimeter sits 3.6% of `vertical_relief` above
`base_height` (33 mm at relief 0.9; ~55 mm at the `PARAM_RANGES` max of 1.5).
`up`/`down` are exact because their edge value is a data extreme. This is both a
contract violation and the residual error in M2.

### M6. `_pyramid_height` over-reports by one step inside the flat margin
`src/myoassist_terrains/velocity_map.py:395`

`int((edge_dist - outer_margin)/step_width) + 1` — `int()` truncates toward
zero, so a small negative argument yields 0 and the `+ 1` promotes it to level 1.
`max(0, ...)` is applied after the `+1` and cannot undo it. Measured: **+0.200 m**
error at the tile edges (2 of 17 probes), exact everywhere else.

---

## Moderate — validation and workflow

### V1. Duplicate `(row, col)` in `tiles` is never rejected
`src/myoassist_terrains/config.py:130-146` validates bounds but not uniqueness.
Verified outcomes:

- same tile type → cryptic MuJoCo `ValueError: Error: repeated name 'flat_r0c0_box' in geom`
- different types → **builds and compiles successfully** with two overlapping
  tiles in one cell; `cell_results[(r,c)]` (`composer.py:284`) keeps only the
  last, so connectors negotiate against the wrong height

### V2. `pyramid_stairs` + `inverted` fails to compile in two unvalidated regions
`src/myoassist_terrains/tiles/pyramid_stairs.py:64-67` validates only
`outer_margin >= 0`. Both of these produce raw MuJoCo errors rather than the
tile-level `ValueError` every other tile provides:

```
outer_margin = 0.0                     -> "size 1 must be positive in geom ..._frame_n"
outer_margin >= tile_size/2  (4.0/8m)  -> "size 1 must be positive in geom ..._frame_e"
```

Cause: zero-thickness frame walls (`:123,130`) and `outer_half_l <= 0` (`:106,138`).
`PARAM_RANGES` caps `outer_margin` at 1.0, so randomization cannot reach it, but
a hand-written config can.

### V3. Boulders can extend past their own cell into the connector strip
`src/myoassist_terrains/tiles/boulders.py:97-113`

`edge_margin` insets the boulder **center**, but each boulder's radii are sampled
independently up to `size_range[1]` (default 0.60 > `edge_margin` 0.50), so the
geometry overhangs. Scan of 200 seeds, 8×8 m tile:

| tile | params | seeds with overhang | worst |
|---|---|---|---|
| `boulders` | defaults | 20 / 200 | +0.091 m |
| `boulders` | `edge_margin=0.2` (PARAM_RANGES min) | **173 / 200** | **+0.391 m** |
| `discrete_obstacles` | `edge_margin=0.2` | 18 / 200 | +0.045 m |
| `stepping_stones` | defaults | 0 / 200 | — |

At the randomization extreme a boulder eats 78% of the default 0.5 m border. All
13 shipped configs were scanned and none currently trips it — latent, but
reachable through `randomization.param_ranges`. `boulders.py:3` says boulders are
"placed within the tile interior (with edge margin)".

### V4. `emit_xml_include` drops `<visual>`, so the CLI and Python-API paths render differently
`src/myoassist_terrains/composer.py:951-954` keeps only `asset` and `worldbody`.
`_build_uniform` sets `spec.visual.rgba.haze` (`composer.py:332-334`) with the
comment "compose propagates this onto the consuming model's `<visual>`".

That comment is true for the sibling repo — `myoassist/myoassist_utils/compose.py:275`
uses `tspec.to_xml()` (full document) and `_inject_terrain_haze` at `:180-192`
picks the haze up. It is **not** true for this package's own CLI. Verified:

```
spec.visual.rgba.haze  = [0.353, 0.439, 0.529, 1.0]
'haze' in emitted XML   = False
compiled waves_preview  -> m.vis.rgba.haze = [1.0, 1.0, 1.0]   (white)
```

So `myoassist-terrains preview` on a uniform terrain shows the white horizon that
the haze line exists to prevent.

### V5. `cmd_preview`'s rationale is wrong and the preview scene has no style
`src/myoassist_terrains/cli.py:110-113` claims the wrapper lives in the library
"so the `../terrain_style.xml` chained-include in the terrain file resolves
correctly". A generated terrain XML contains **zero** references to
`terrain_style.xml` — nothing in the emit path adds one. Verified on the README
quickstart terrain:

```
first_terrain_preview.xml -> ngeom=26  nhfield=1  nmat=10  nlight=0  ntex=0
```

The documented visual-QC path therefore renders with no skybox, no lights and no
textures (black void, default headlight only). It also declares no
`<visual><global offwidth/>`, so `mujoco.Renderer` is capped at 640×480.
The asset paths do resolve correctly from the library dir, so the file loads.

### V6. Unknown top-level config keys are silently ignored
`src/myoassist_terrains/config.py:245-345` reads every field through
`raw.get(...)`. Verified:

```
{"terrain":"sinusoidal","amplitud":0.9,"perod":3.0,"nonsense":true}
  -> builds a default 0.1 / 1.0 surface, no warning

{"boarder":{"width":0.9},"pallete_preset":"uniform","textrue":"x.png", ...}
  -> border.width=0.5, palette_preset='diverse', texture=None, no warning
```

Typos in *tile* params do fail loudly (`TypeError: emit() got an unexpected
keyword argument 'heght'`), so the gap is specific to top-level keys — including
every field of the uniform form, where a mistyped `amplitude` silently yields a
near-flat surface.

### V7. A `texture` block is silently ignored unless `palette_preset == "uniform"`
`src/myoassist_terrains/composer.py:661-678` binds the texture only in the
uniform branch. Verified: `palette_preset="diverse"` plus a texture pointing at a
**nonexistent file** emits no `<texture>`, raises nothing, and warns nothing. The
same missing file is a hard `FileNotFoundError` in uniform mode
(`composer.py:175-179`). `docs/concepts.md:41` correctly scopes the feature to
uniform mode, but a misconfigured user gets no signal.

### V8. `palette` overrides are discarded in the grid uniform preset but honoured in the uniform-terrain path
`composer.py:711-718` computes `rgba` from `config.palette[type_name]` and then
returns `uniform_rgba` instead, discarding it. `_resolve_uniform_appearance`
(`composer.py:358-370`) *does* honour `palette`. Verified: grid
`palette_preset="uniform"` + `palette={"flat":[0.9,0.1,0.1,1]}` → geom rgba stays
`[0.78, 0.78, 0.78, 1.0]`, silently.

### V9. `_UNIFORM_RGBA` is out of sync with the style file it claims to mirror, and `output_dir` changes the colour
`composer.py:56-59` says "Mirror the rgba of the style file's `terrain_mat` … If
you retune terrain_mat's rgba in terrain_style.xml, update this constant to
match." It does not match:

| source | rgba |
|---|---|
| `composer._UNIFORM_RGBA` | `0.78 0.78 0.78 1` |
| `utils/style/terrain_style.xml:24` | `0.31 0.663 0.667 1` |
| `utils/render/terrain_style.xml:17` | `0.792 0.996 1 1` |

Because `_read_uniform_rgba_from_style` returns the constant when
`output_dir is None` (`composer.py:122-123`), the **same config** produces
different colours through the two entry points — verified `0.31/0.663/0.667` with
`output_dir`, `0.78` grey without.

### V10. Publishing can ship an untested tree; no version bump, no tags, no changelog
`.github/workflows/publish.yml`

- `build` has no `needs:` on the test job, so `workflow_dispatch` can publish a
  tree with failing tests or lint.
- It builds with `uv build` while `test.yml:40-50` verifies with `python -m build`
  — two different build paths, only one of which is checked.
- No version-vs-PyPI guard. `version = "0.1.0"` was set in the initial commit
  (`25d0b93`, 2026-05-15) and has never changed, so the next dispatch fails with
  an opaque PyPI 409.
- `git tag` is empty and there is no `CHANGELOG`, so nothing records what was
  published. The consumer pins `myoassist-terrains>=0.1.0`
  (`myoassist/requirements.txt:31`), which cannot distinguish tree states.
- `uv.lock` is committed but CI installs with `pip install -e ".[dev]"`, so the
  lock file is never exercised.

(The published 0.1.0 dates from 2026-08-11, after `config_from_dict` and the
uniform form landed, so there is no broken published combination today.)

### V11. CI never runs on Windows/macOS, nor above Python 3.12
`.github/workflows/test.yml:12,16` — `ubuntu-latest`, matrix `3.10–3.12`.
`requires-python = ">=3.10"` is unbounded and classifiers stop at 3.12, so 3.13+
installs are permitted but untested. Notably the code carries three
Windows-specific `.replace("\\", "/")` workarounds (`composer.py:189`,
`rough.py:176`, `tests/test_examples.py:38`) whose platform CI never exercises,
and the primary development machine is Windows. Add `windows-latest` on at least
one Python version.

### V12. Documented render tooling is gitignored and cannot run from a fresh clone
`.gitignore:228-233` ignores `utils/render/26muscle_3D`, `utils/render/mesh`,
`utils/render/terrain_config.xml`, and both `myoassist_ensemble*` configs, while
`docs/utilities.md:49-50` documents `mesh/` and `terrain_config.xml` as repo
contents. All six tracked `ensemble_*.json` reference
`26muscle_3D/myoLeg26_*.xml`.

Verified from the tracked tree: `render_velocity_map.py` and
`render_terrain_check.py --config utils/render/terrain5x5_velocity.json` both
work (both documented in `docs/velocity-maps.md`) — because
`terrain5x5_velocity.json` references only tracked paths. Not runnable:
`render_ensemble.py` with any shipped config, and the third example in
`render_terrain_check.py:18-20` (`--config ensemble_velocity.json`, which loads
models). Either commit the render fixtures, or say plainly in
`docs/utilities.md` which scripts need local-only assets.

### V13. `*_terrain_assets/` generated directories leak into `git status`
`utils/render/render_ensemble.py:512` and `render_terrain_check.py:48` both
derive the directory from `scene_name` (`f"{scene_name}_terrain_assets"`), but
`.gitignore:231-232` lists only two hard-coded names. Running the **documented**
`render_terrain_check.py` command left an untracked
`utils/render/terrain5x5_velocity_terrain_assets/` with 60+ PNGs.
Fix: `utils/render/*_terrain_assets/`.

### V14. Registering a custom tile breaks velocity maps
`velocity_map.py:96` asserts a `DEFAULT_SPEED_SCALE` entry exists;
`registry.register_tile` (`registry.py:23-38`) offers no way to supply one.
Verified: a custom tile builds and compiles fine, then
`generate_velocity_map` → `AssertionError: missing speed scale for tile type
'my_tile'`. `docs/extending.md:28` promises `"my_tile"` "is a valid `"type"`
value in any config". Either give `register_tile` a `speed_scale` argument or
fall back to a default with a warning.

### V15. `velocity_map` validates with bare `assert`
`velocity_map.py:68-79, 94, 96, 189, 200, 243, 258, 269-271, 345, 406`;
`velocity_arrows.py:21, 110, 125`. The rest of the package raises `ValueError`.
Under `python -O` every one of these vanishes: the `mode` and `tile_radial_mode`
spelling checks disappear silently, and V14 degrades from a clear
`AssertionError` to `speed = base_speed * None * ...` → `TypeError`.

### V16. `generate_velocity_map` on a `UniformTerrainConfig` fails internally
Verified: `AttributeError: 'UniformTerrainConfig' object has no attribute 'grid'`.
No type check, and `docs/velocity-maps.md` never states the restriction.

### V17. `samples_per_tile=1` places the sample far off centre
`velocity_map.py:168-170` — `np.linspace(a, b, 1)` returns `[a]`, so the margin
becomes the position:

```
_sample_offsets(10.0, 1) = [-3.2]        -> sample at (-3.2, -3.2) on a 10 m tile
_sample_offsets(10.0, 2) = [-4.1, 4.1]
_sample_offsets(10.0, 3) = [-4.4, 0.0, 4.4]
```

Two of the four existing velocity-map tests use `samples_per_tile=1`, so the
suite is anchored on the off-centre behaviour.

### V18. `add_velocity_overlay` crashes on an empty sample list
`velocity_arrows.py:118-120` → `ValueError: min() iterable argument is empty`.

### V19. List-valued tile params cannot be set through `param_ranges`
`composer.py:570-581`: `_is_numeric_range([0.2, 0.6])` is `True`, so a user
writing `param_ranges: {"boulders": {"size_range": [0.2, 0.6]}}` (intending to
fix the range) gets a **scalar** back, which then hits `tuple(float)` →
`TypeError` inside the tile. Affects `boulders.size_range`,
`discrete_obstacles.size_range` and `.height_range`. There is no escape syntax.

### V20. Reversed float ranges are accepted silently; reversed int ranges raise
`composer.py:588-594`. The int branch raises on `hi < lo`; the float branch calls
`rng.uniform(lo, hi)`, which silently samples `[hi, lo)`.

### V21. `terrain_name` is used verbatim as a path component
`cli.py:47`. Verified: `terrain_name: "../escaped"` prints
`Wrote terrain\..\escaped.xml` and writes the file *outside* the library, where
`set-active` cannot find it. Low risk (self-inflicted, config-driven) but a
one-line name check removes it.

---

## Documentation

### D1. The entire uniform-terrain config form is undocumented here
`docs/configuration.md` and `docs/concepts.md` never mention the top-level
`"terrain"` key or any of `deg`, `amplitude`, `period`, `seed`, `extent`,
`resolution`, `safe_zone_radius`, `base_depth`. The README Contents list omits it
too. It is a full second config form: 114 LOC in `uniform.py`, a dispatch branch
in `config.py`, a build path in `composer.py`, and the largest test file
(`test_uniform.py`, 276 lines).

The **downstream repo documents it instead** —
`myoassist/docs/reinforcement-learning/03_terrain-types.md:21-31` carries the
table of `{"terrain": "flat"|"slope"|"random"|"sinusoidal"}` forms that this
repo's own schema reference is missing. Highest-value doc fix in the list.

### D2. `docs/tiles.md:3` — "All angles in radians unless noted"
No tile parameter is in radians. `slope.angle_deg` and `UniformTerrainConfig.deg`
are degrees; the table at `:32` says so. The blanket statement is backwards.

### D3. `density` is documented as an area fraction; it is a count per m²
`docs/tiles.md:75` and `:101` both say "Approximate fraction of tile area
covered by …". The code is `n = round(density * tile_area)`
(`discrete_obstacles.py:95`, `boulders.py:95`), and the `DEFAULT_PARAMS` comments
say "obstacles per m²" / "boulders per m²". Two entirely different quantities.
(Also: the count uses the *full* tile area while placement is confined to the
`edge_margin` inset, so the realised density is higher than requested.)

### D4. `boulders` docs describe the wrong shape and understate size 2×
`docs/tiles.md:97` "Randomly placed half-sphere boulders" — they are ellipsoids
with independently sampled per-axis radii (`boulders.py:105-107`).
`docs/tiles.md:102` "Min/max boulder **diameter**" — `size_range` feeds MuJoCo
ellipsoid `size`, i.e. **radii**. `discrete_obstacles.size_range` genuinely is a
full side length (`discrete_obstacles.py:105-106`), so the two tiles interpret
the same-named parameter differently and only the `boulders` row is wrong. This
understatement is what makes V3 easy to miss.

### D5. `docs/tiles.md:71` — "Randomly placed boxes at random heights (cones, blocks)"
Only `mjGEOM_BOX` is emitted. No cones.

### D6. `rough` docs and docstrings describe only `relief_mode="up"`
`rough.py:7-9` ("values are 0 at the boundary"), `rough.py:13` ("value 1.0
reaches base_height + vertical_relief"), `rough.py:14` ("base_z = base_height −
BASELINE_Z"), and `docs/tiles.md:66` ("taper to 0 at tile edge") are all true
only for `"up"`. The default is `"centered"`, where the edge value is 0.5 and the
geom origin is `base − relief/2`. `docs/tiles.md:59` ("Total `[min, max]`
heightmap range, scaled by `hfield_size_z`") is circular: `vertical_relief`
*is* `size[2]`.

### D7. `rough.py:144-150` documents a parameter that does not exist
The comment block explains `invert_relief=False` / `invert_relief=True`. The
parameter is `relief_mode` with three values. Stale from a refactor.

### D8. `composer.py:382-385` — sign error in the slope-plane derivation
The docstring says the rotation "maps the plane's local +z normal to
`(sin(deg), 0, cos(deg))`". Measured for `deg=15`:
`(-0.25882, 0.00000, +0.96593)` = `(-sin(deg), 0, cos(deg))`. The conclusion
(`z = tan(deg)·x`, uphill in +x) is correct and the code is correct — only the
intermediate step is sign-flipped, which makes the reasoning impossible to
follow.

### D9. `_build_uniform` claims to track `terrain_style.xml`; it does not
`composer.py:322-324` ("one shared material … whose rgba tracks
`terrain_style.xml`") and `config.py:167` ("rgba tracks `terrain_style.xml`").
`_build_uniform` never calls `_read_uniform_rgba_from_style`: the material is
hardcoded `[1,1,1,1]` (`composer.py:336-342`) and the geom defaults to white so
the matfloor texture shows through unmodulated. Only the *grid* path reads the
style file.

### D10. `palette_preset: "custom"` is a documented mode with no behaviour
`docs/concepts.md:39`, `docs/configuration.md:21-26`. Verified: `"custom"` and
`"diverse"` produce **byte-identical** XML, both with and without a palette
override — `_resolve_appearance` (`composer.py:711-718`) never branches on it.
Either give it distinct semantics or document it as an alias.

### D11. `docs/python-api.md` inaccuracies
- `:26` and `:28` describe `build_terrain` and `load_config` as `TerrainConfig`-only; both handle `UniformTerrainConfig`.
- `:32` calls `tiles.REGISTRY` "Read-only" — it is a plain mutable dict that `register_tile` writes to.
- `config_from_dict` is **absent from the table**, although `__init__.py:10-11` advertises it, its own docstring calls it the public companion to `load_config`, and the downstream consumer imports it (`myoassist/myoassist_utils/compose.py:33`, `env_spec.py:123`).
- `:19` `write_text(xml)` omits `encoding="utf-8"`, unlike `cli.py:49`.

### D12. `docs/development.md:9-12` misdescribes the test suite
It claims coverage of "the composer (layouts, palette resolution, sample terrain
build)" — `compute_cell_layouts` has **no test at all** — and omits both
`test_uniform.py` (the largest test file) and `test_examples.py`.

### D13. `docs/utilities.md` content errors
- `:13` `myoassist_base.json` "all nine tile types" — it uses **seven** (no `flat`, no `gap`); it is a 3×3 grid of nine *cells*.
- `:11` `m{2,3,4,4b,5}_*.json` "Single-tile-type demos" — `m2` has 3 types, `m3` has 4, `m4` has all 9, `m5_mixed`/`m5_random` are randomized.
- `:45` `camera_convert.py` "Convert MuJoCo camera XML ↔ the pos/xyaxes JSON" — only XML→JSON exists; there is no reverse function.
- `:49-50` documents `mesh/` and `terrain_config.xml`, both gitignored (V12).

### D14. `utils/style/terrain_config.xml:16` — corrupted command name
Reads "Running `myoassGreist_terrains build`". Should be `myoassist-terrains build`.
This file is the shipped user-project template. The same comment block also
refers to `26muscle_3D/myoLeg26_*.xml` model paths, while
`docs/project-layout.md:14-15` shows the template layout as `models/my_model.xml`.

### D15. `utils/configs/_make_tiled.py:1` — wrong output size
"build a 3x3 tiled JSON from a 3x3 base config"; it builds a **9×9** (line 3 says
so correctly, as does `docs/utilities.md:23`).

### D16. `gap.axis` and `stairs`/`slope`.`axis` mean opposite things, documented identically
`docs/tiles.md:20` "Axis the staircase runs along" vs. `:113` "Axis the gap runs
along". For `stairs`/`slope`, `axis="y"` means the feature *progresses* along y
(you cross it walking in y). For `gap`, `axis="y"` means the trench is
*invariant* along y and you cross it walking in x — `gap.py:11-13` and `:64-72`
are explicit about this, `docs/tiles.md` gives no way to tell them apart. A
`randomization.param_ranges` entry fixing `axis: ["y"]` across types yields
mixed orientations.

### D17. Internal milestone codes in user-facing text
`flat.py:59` raises "For tiles meant to dip below baseline, use a `gap` tile
(M4)." — a runtime error message citing an internal milestone. Also
`tiles/base.py:6` "(M5)". No M-numbers appear anywhere in `docs/`.

### D18. `myoassist_tiled.json` filename ≠ its `terrain_name`
`terrain_name` is `myoassist_base_tiled3x3`, so `set-active myoassist_tiled`
fails and `set-active myoassist_base_tiled3x3` is required. Not documented in
`docs/utilities.md:14`.

### D19. `stairs.peak_width` has two different defaults
`DEFAULT_PARAMS` is `0.40` (`stairs.py:37`, which is what the composer merges and
what `docs/tiles.md:21` documents); the `emit` signature default is `0.25`
(`stairs.py:66`). Only direct `emit` callers see the second value.

### D20. `docs/velocity-maps.md:8` cites "the paper's Fig. 3(b)"
An unpublished internal reference in public-facing documentation.

### D21. `tiles/base.py:9-10` names the wrong module for the registry
It says the composer looks tiles up via `myoassist_terrains.registry.REGISTRY`;
`registry.py:3-5` says the dict lives in `myoassist_terrains.tiles.REGISTRY`. The
composer imports both `registry.lookup` and `tiles.REGISTRY`.

### D22. Spelling and style drift
Docs use British forms ("centred", "randomisation", "colour", "metres",
"neighbouring") against American forms in code and config keys ("center",
"randomization", "color"). 14 em dashes remain across `README.md` (10),
`docs/concepts.md` (1), `docs/utilities.md` (1) and `docs/velocity-maps.md` (2),
against the project's ASD-STE100 no-em-dash convention — consistent with the
STE sweep already noted as outstanding.

---

## Dead code, structure and efficiency

| # | Finding |
|---|---|
| N1 | `_emit_terrain_floor(spec, config, cell_results)` — `cell_results` never read (`composer.py:840`). |
| N2 | `_register_palette_materials(..., uniform_rgba=...)` — never read (`composer.py:651`); the uniform branch hardcodes white. `build_terrain:247-248` computes and passes it anyway. |
| N3 | `_emit_flat_box(..., geom_name=None)` — no caller ever passes it (`composer.py:879`). |
| N4 | `rough.emit(..., asset_path_prefix="../terrain")` — never used (`rough.py:79`). It reads like a per-tile knob for the emitted asset path, but the rewrite happens in `emit_xml_include(hfield_relpath_prefix=...)`; setting it in tile params silently does nothing. |
| N5 | `TileEmitResult.boundary_heights` (`base.py:41-46`) is read nowhere; `_match_heights` ignores it. Documented as a v2 hook. |
| N6 | `config._texture_from_raw` (`config.py:264-276`) is used by the uniform branch, but `_grid_config_from_dict:322-334` re-implements it verbatim. Two copies to keep in sync. |
| N7 | `_emit_terrain_floor`'s docstring calls the backstop "an invisible backstop plane"; it emits a finite **box** (`composer.py:842, 863`). |
| N8 | `_tile_direction_xy` has two consecutive `if` blocks with identical bodies (`velocity_map.py:222-232`). |
| N9 | `surface_height_at` rebuilds `compute_cell_layouts(config)` on every call (`velocity_map.py:333`) and is called 5× per sample (1× `_direction_and_grade`, 4× `_local_surface_roughness`) — ~12.5k dict rebuilds plus linear tile scans for a 5×5 grid at `samples_per_tile=10`. Hoist the layout map and index tiles by `(row, col)`. |
| N10 | `_smooth_sample_speeds` is O(N²) per iteration (`velocity_map.py:279-288`); N = rows·cols·samples_per_tile². The shipped 15×15 velocity render produces 8100 samples → ~131M distance evaluations over 2 iterations. |
| N11 | `_register_palette_materials` declares a material for **every** registry entry regardless of use — verified 10 materials emitted for a single-`flat`-tile terrain. |
| N12 | `noise.py:15` uses `typing.Tuple` while the rest of the package uses builtin `tuple` under `from __future__ import annotations`. |
| N13 | `noise.edge_taper`'s docstring says `taper_frac` is a fraction "of the shorter axis" (`noise.py:65`); it is a per-axis fraction of each axis independently (`:72-76`). Equivalent only for square arrays, which is all `rough` uses. |
| N14 | Terrain XML is built through `MjSpec`, arrow XML through raw `ElementTree` (`velocity_arrows.py`) — two construction styles in one package. |
| N15 | `utils/configs/_make_tiled.py` and `utils/render/camera_convert.py` have no `if __name__ == "__main__"` guard and execute at import. `_make_tiled.py:14` reads `sys.argv[1]` unguarded (`IndexError`, no usage message); `camera_convert.py:30-37` runs a hardcoded example and has no CLI, so the "converter" requires editing the source. |
| N16 | `_make_tiled.py:29-39` `rotate_rc` mixes row and column extents, so a non-square base silently yields out-of-grid coordinates (later rejected by `TerrainConfig.__post_init__`). `_make_tiled_rings.py:57` asserts the 3×3 shape; `_make_tiled.py` does not. |
| N17 | `render_terrain_check.py:37` imports `render_ensemble` and reaches into its privates (`_load_config`, `_resolve_path`, `_build_styled_terrain`, `SceneBuilder`, `TemplateModel`) plus its re-exported `add_velocity_overlay`, while also importing from the package directly at `:34-35`. |
| N18 | `render_terrain_check.py:131` writes its temp scene into `utils/render/` (`dir=base_dir`, `delete=False`); a kill between write and unlink leaves an untracked `tmp*.xml` in the tree (not gitignored). |
| N19 | `render_ensemble._deepcopy` (`:53-55`) is a pass-through wrapper whose docstring calls it "Efficient shorthand". |
| N20 | `cli.cmd_list(args)` — `args` unused (`cli.py:142`). No `--version` flag despite `__version__` being public. No `--root`/`--output-dir` override, so `build` always requires a discoverable `terrain_config.xml`. |
| N21 | `pyproject.toml:59-66`: `select = ["E","F","W"]` with the comment "mirrors assist_sim / myo_sim so tooling is consistent across repos". It matches `assist_sim` but **not** `myo_sim`, which adds `"I"` plus a `[tool.ruff.lint.isort]` section — and this tree has **23 files with unsorted imports** as a result. A broader scan also surfaces 27 `ARG001` (N1–N4 among them). `extend-exclude` lists `"external"`, a directory this repo does not have. |
| N22 | `_box_z_span` (`composer.py:746-752`) imposes an undocumented hard floor: any tile with `base_height <= BASELINE_Z = -2.0` fails at connector emission. `docs/concepts.md:22` mentions `BASELINE_Z` only as the connector bottom, never as a limit on `base_height`. |

---

## Test coverage

| # | Gap |
|---|---|
| T1 | **Zero coverage for `cli.py` (207 lines) and `paths.py` (66 lines)**: no test of `cmd_build`, `_set_active`'s regex, `cmd_list`, `cmd_preview`, `main`, the env-var override, or the walk-up failure. M3 and V21 both live in this blind spot. |
| T2 | **No test measures the emitted surface.** M4, M5 and V3 are all invisible to the suite. One ray-cast fixture asserting "perimeter z == base_height for every tile type, at defaults" catches all three and locks the contract down. |
| T3 | **No test compares `estimate_surface_height` to the emitted geometry** — M1, M2 and M6 all live here. The same fixture as T2 covers it. |
| T4 | `test_examples.py:21-24` returns `[]` when the configs dir is missing, and an empty `parametrize` list **passes silently** — the test can become a no-op without failing. Assert the list is non-empty. |
| T5 | `test_uniform.py:23` imports the private `_config_from_dict`; the public `config_from_dict` (added specifically so consumers stop reaching for the private one) has **zero** coverage, despite being what the downstream repo imports. |
| T6 | `compute_cell_layouts` has no test, though `docs/development.md` claims layout coverage. |
| T7 | `emit_xml_include`'s `hfield_relpath_prefix` / `texture_relpath_prefix` parameters are untested. |
| T8 | `border.match_mode` (`min`/`max`/`mean`) and connector geometry are untested — `test_tiles.py` and most of `test_composer.py` use `border.width = 0.0`. |
| T9 | No test covers the emitted-XML path for uniform terrains. `test_flat_matches_legacy_matfloor_styling` checks the compiled spec's haze, so V4's loss inside `emit_xml_include` is invisible. |
| T10 | `test_composer.py:126-139` mutates `cfg.randomization` after construction, with a comment claiming it avoids the "tiles OR randomization" guard. That guard only fires when `tiles` is empty (`config.py:135`), so passing `randomization` to the constructor works fine — the comment is wrong and the mutation bypasses `__post_init__`. |
| T11 | `test_velocity_map.py:29` collapses samples into `{tile_type: speed}`, keeping only the last sample per type, so the assertion tests one arbitrary sample. |
| T12 | `test_tiles.py:28-29` comment says "gap with default gap_width consumes most of a 1m tile"; the test uses 4.0 m tiles. |
| T13 | `pytest-cov` is a dev dependency and `pytest --cov` is documented (`docs/development.md:6`), but no coverage config or CI gate exists. |
| T14 | `test_registry.py:26` uses `issubset`, so a stray registry entry passes unnoticed. |

---

## Suggested order of work

1. **M3** (one line) and **M6** (one line) — smallest fixes with real payoff.
2. **T2/T3**: add the ray-cast fixture *before* fixing M1, M2, M4, M5, so the fixes are proven and the contract stays locked.
3. **M1, M2** — the velocity map currently misdescribes the terrain it is generated from.
4. **M4, M5** — decide whether the flat-at-base contract is a real invariant. If yes, fix stairs auto-fill (reserve one `step_width` of margin, or report the true edge height in `TileEmitResult`) and compensate `rough` for renormalization the way `_emit_uniform_hfield` already does. If no, rewrite `docs/concepts.md:25-29` to state the exceptions.
5. **D1** — document the uniform form; it is the largest single doc gap, and the downstream repo is currently carrying it.
6. **V1, V2, V3, V19** — validation, cheap and self-contained.
7. **V10, V11, V13** — release and CI hygiene: gate publish on tests, add `windows-latest`, glob the assets ignore.
8. The remaining docs pass (D2–D22), then the dead-code sweep (N1–N4, N6) with `ARG` and `I` added to the ruff `select` list so it does not recur.

---

*This file is a review artifact, not part of the package. Delete it (and the
stale untracked `review.md` from the earlier `docs-restructure` review) when done.*

---
---

# Addendum A — do the majors reproduce through myoassist?

Driven through `myoassist_utils.compose.compose_env_model` and
`myoassist_utils.env_spec.EnvSpec` (`myolegs22` + `DephyExoBoot_L1`), the shared
path both RL (`rl_train/envs/environment_handler.py:115-126`) and CO
(`ctrl_optim/ctrl/reflex/reflex_interface.py:230`) funnel through.

## Not reachable through myoassist

**M1, M2, M6** (the `velocity_map` height-model bugs) and **M3** (the `-m` exit
code). myoassist contains **zero** references to `velocity_map` / `velocity_arrows`
and never shells out to the terrains CLI. Their only consumers are this repo's
`utils/render/` figure pipeline and `utils/configs/_rebuild_myoassist.py`. That
lowers their blast radius but not their severity for the paper figures.

## Reproduce unchanged through compose

| ID | Confirmed through `compose_env_model` |
|---|---|
| M4 | stairs tile perimeter measured at `+0.1500` (both y-edges), peak `+0.9000`. Contract violation survives compose. |
| M5 | rough perimeter measured `[+0.0324, +0.0337]` instead of `0.0000`. |
| V1 | `EnvSpec.validate()` **passes** a duplicate `(0,0)` cell; `compose_env_model` then succeeds with 86 geoms and two overlapping tiles. |
| V2 | `EnvSpec.validate()` **passes** `pyramid_stairs` `inverted` + `outer_margin=0`; `compose_env_model` dies with `ValueError: size 1 must be positive in geom 'pyramid_stairs_r0c0_frame_n'`. |
| V9 | uniform-preset tile rgba through compose = `[0.78, 0.78, 0.78, 1.0]`, the fallback constant. `compose` passes a **temp** assets dir, so `<assets_dir>/../terrain_style.xml` never exists and the style file is *never* read on this path. |

## V6 is worse than reported: silent terrain substitution in the authoring path

The inline-dict terrain is exactly how RL and CO configs specify terrain. A typo
passes `EnvSpec.validate()` and silently trains on the wrong ground:

| inline spec | intent | realised |
|---|---|---|
| `{"terrain": "slope", "dge": 8.0}` | 8° incline | `-0.000°` — flat |
| `{"terrain": "random", "amplitud": 0.35}` | 0.35 m relief | `0.1000` m — the default |

Nothing downstream cross-checks it: `env_spec.slope_deg_from_terrain` reads the
same misspelled dict, so the eval follow-camera and the cost function agree with
the wrong terrain. This is a silent-wrong-science path, not a crash.

## NEW — N-X1. Terrain with real geometry is misseated through compose

> **CORRECTED after prototyping the fix.** This is not grid-specific. `uniform
> random` (a single heightfield) is broken too. The real split is **plane-based
> terrain works, everything with finite or heightfield geometry does not** —
> `flat`/`slope` escape because plane-mesh distance stays exact at any margin.
> Also, the one-line margin reduction suggested at the end of this section is
> **inadequate**: measured across 9 terrains, `margin=20` fixes only 2 of the 6
> broken cases. See `REVIEW_DECISIONS.md` → "N-X1 (REVISED)" for the fix that was
> actually adopted: `myoassist_terrains` exports `surface_height_at` /
> `max_surface_height_in`, and `compose` consumes it instead of collision-probing.


Not in the original report; found during this pass and more severe than anything
in it.

| terrain | root_z after compose | lowest foot vertex | verdict |
|---|---|---|---|
| `terrain=None` (compose default) | `+0.9589` | `-0.0050` | correct |
| `{"terrain":"flat"}` (uniform/plane) | `+0.9589` | `-0.0050` | correct |
| `{"terrain":"slope","deg":8}` | `+0.9664` | `+0.0026` | correct |
| grid `flat` tile | `-0.6430` | `-1.6068` | **buried 1.6 m** |
| grid `stairs` | `-0.6423` | `-1.6062` | **buried 1.6 m** |
| `flat_smoke_test.json` (shipped) | `-1.6217` | `-2.5855` | **buried 2.6 m** |
| `myoassist_base.json` (shipped) | `-0.6423` | `-1.6062` | **buried 1.6 m** |
| `m4_demo.json` (shipped) | `+24.9873` | `+24.0235` | **launched 24 m up** |

The buried model does not error: it pops out over ~200 steps
(`root_z -> -0.054`, `max|qvel| = 2.79`, 0 MuJoCo warnings), so an episode just
starts from garbage.

**Mechanism.** `compose._seat_dz_by_collision` sets `geom_margin = 50.0`
(`compose.py:121`) and takes `min(contact.dist)` over all terrain↔model pairs.
The unseated model is already almost right (`root_z=+0.9600`, lowest foot vertex
`-0.0039`, true `dz = -0.0011`). Sweeping the margin on that same model:

```
 margin   min(gap)        dz   winning pair
   0.00   -0.00387   -0.0011   flat_r0c0_box <-> tb_toe_l_geom      OK
   5.00   -0.00387   -0.0011   flat_r0c0_box <-> tb_toe_l_geom      OK
  20.00   -0.00387   -0.0011   flat_r0c0_box <-> tb_toe_l_geom      OK
  30.00   +0.02391   -0.0289   ...                                  OK
  50.00   +1.59796   -1.6030   flat_r0c0_box <-> tb_shank_r_geom    BROKEN
```

At margin 50 MuJoCo's mesh↔large-box narrowphase stops returning a physical
separation (the same run reports `tibia`/`femur` gaps of `+1.32…+1.35` while
`thorax` reads `-0.39` — geometrically impossible for a true signed distance), so
the minimum lands on the wrong pair. Plane-based terrain escapes it because
plane↔mesh distance stays exact at any margin.

I first suspected the `terrain`-named backstop hijacking the model's foot contact
pairs. That was wrong and is ruled out: the composed model has **zero** `<pair>`
entries referencing `terrain`, and all six foot geoms carry
`contype=1 conaffinity=1`, so they can and do collide with the tile.

**Where the fix belongs: both sides.** `myoassist_terrains` gains public
`surface_height_at(config, x, y)` and `max_surface_height_in(config, x, y, radius)`
queries (cheap given M1's tile-owned `surface_height`), and `compose` measures the
model's lowest foot vertex exactly and subtracts, dropping the collision probe on
the terrain side entirely. That removes the magic constant and the MuJoCo-version
dependence. Superseded options and prototype measurements are recorded in
`REVIEW_DECISIONS.md`.

---

# Addendum B — documentation scoping vs. `myoassist-web`

Topology decision for this pass: **`myoassist-web/modeling/terrains/` is canonical
for user-facing prose; `myoassist.terrains/docs/` is the developer/API reference.**
Sync facts, not prose.

`myoassist-web` is on branch `compose-1.0-docs` with 4 uncommitted modified files
under `controller-optimization/`. Nothing was written to it.

## What the website already has

`modeling/terrains/` — `index.md` (74), `configuration.md` (70),
`tile-types.md` (205), `velocity-maps.md` (93). It is a **faithful STE-cleaned port
of the local docs plus per-tile render figures** — the 205 vs. 114 line difference
in the tile catalog is figure markup, not extra content. Already fixed there and
still wrong locally:

- em dashes removed, American spelling, shorter active sentences (the STE pass)
- D5 fixed: "Randomly placed boxes at random heights" (local still says "(cones, blocks)")
- D20 fixed: the "paper's Fig. 3(b)" reference is gone

## Errors duplicated on the website (fix in both places)

| Local ID | Website location | Note |
|---|---|---|
| M4 / M5 | `tile-types.md:12-14`, `index.md:49-53` | The false boundary contract, stated **more strongly** on the website: "so tiles always join cleanly". |
| D2 | `tile-types.md:11` | "All angles are in radians unless noted" — nothing is in radians. |
| D3 | `tile-types.md:136, 180` | `density` as "Approximate fraction of tile area covered" — it is a count per m². |
| D4 | `tile-types.md:174, 181` | "half-sphere boulders" / `size_range` as "diameter" — ellipsoids, and the range is radii. |
| D6 | `tile-types.md:111, 118` | `vertical_relief` "scaled by `hfield_size_z`" (circular) and "taper to 0 at the tile edge" (only true for `relief_mode="up"`). |
| D10 | `index.md:63` | `custom` presented as a distinct mode; it is byte-identical to `diverse`. |
| V9 | `index.md:62` | "Every tile shares the color of `terrain_mat` from `terrain_style.xml`" — **never true through myoassist**, because compose passes a temp assets dir (Addendum A). Worse on the website, whose audience only reaches terrain through compose. |

## Website-only error (not present locally)

**`configuration.md:13-14` — "Only `terrain_name` and `grid` are required."**
Verified false: `config_from_dict({"terrain_name": "x", "grid": {...}})` raises
`ValueError: Config must include either 'tiles' … 'randomization' … or both`.

## D1 (the uniform form) — partially covered, schema still missing everywhere

The website does not ignore the uniform form: `index.md:17-19` defers it to
`getting-started/defining-an-environment.md:81-86`, which carries a 4-row table
covering `flat`, `slope`+`deg`, `random`+`amplitude`, `sinusoidal`+`amplitude`/`period`.

But **no copy anywhere documents** `seed`, `extent`, `resolution`,
`safe_zone_radius`, `base_depth`, `terrain_name`, `palette`, or `texture` on the
uniform form. Given that RL/CO runs are authored with inline uniform dicts and
V6 silently swallows typos, the missing `resolution` / `extent` /
`safe_zone_radius` fields are the ones users most need.

## Proposed split

**Website (`myoassist-web`, user-facing) — scoped, not written this pass:**

1. Fix the 7 duplicated errors above plus the website-only `configuration.md:13-14` claim.
2. Add a uniform-terrain schema table — either a new `modeling/terrains/uniform.md` or a field table appended to `defining-an-environment.md:86`.
3. Re-word the boundary contract to state its exceptions (pending the M4/M5 decision — if those are fixed in code, the current wording becomes true and needs no change).
4. Note in `index.md:62` that the `terrain_mat` pickup only applies to the CLI/`output_dir` path, not to compose (or drop the claim once V9 is resolved).

**Local (`myoassist.terrains/docs/`, developer reference):**

5. Keep and fix: `cli.md`, `python-api.md`, `extending.md`, `development.md`, `project-layout.md`, `utilities.md` — these have no website counterpart and are where D11, D12, D13 live.
6. Fix the same 7 shared factual errors in `concepts.md`, `configuration.md`, `tiles.md`, `velocity-maps.md`, then add a one-line pointer at the top of each: user-facing docs live on the website.
7. `velocity-maps.md` stays local-only in substance — the subsystem has no myoassist consumer at all (Addendum A), so it is developer/figure-pipeline documentation.
8. Apply the STE pass locally (14 em dashes, British spellings) so the two copies stop diverging on style.

**Third copy:** `myoassist/docs/reinforcement-learning/03_terrain-types.md` overlaps
both and is the only place the uniform form is tabulated inside the myoassist repo.
Recommend retiring it in favour of the website page once (2) lands; out of scope
for this pass.
