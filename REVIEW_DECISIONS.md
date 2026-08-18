# Review decision log

Companion to `FRAMEWORK_REVIEW.md`. Records what was decided, why, and what it
costs. Updated as each batch is settled. Supersessions are kept visible rather
than edited away.

Status: **implemented.** See the implementation status at the end of this file.

---

## Session-level

| ID | Decision | Rationale |
|---|---|---|
| S1 | ~~Write scope is `myoassist.terrains` only.~~ **AMENDED:** `myoassist` is in scope and **nothing critical is deferred**. `myoassist-web` remains scoped-not-written (it has uncommitted work on `compose-1.0-docs`). | The seating defect (N-X1) is critical and cannot be fixed from one side alone. Docs remain a changelist because the website branch is mid-flight. |
| S2 | Docs topology: **`myoassist-web/modeling/terrains/` is canonical for user-facing prose; `myoassist.terrains/docs/` is the developer/API reference.** Sync facts, not prose. | The website copy is already STE-clean and carries the figures. Duplicating prose is what let the two drift. |
| S3 | Cross-repo verification driven through the `compose_env_model` / `EnvSpec` chokepoint plus a live env, not full CO/RL runs. | Both pipelines funnel through it (`environment_handler.py:115-126`, `reflex_interface.py:230`), so it covers both without guessing run configs. |
| S5 | Terrain outputs must remain compatible with the myoassist/assist_sim compose cache; no training-speed regression. See the S5 section below. | Verified the cache is worth 68x and that grid+`rough` currently breaks it. |
| S4 | Pacing: the six Majors discussed individually; Moderates in four themed batches; docs / nits / tests one batch each. | The Majors carry real design forks — M1 and M4 both changed shape under discussion. The rest are mostly "do it or don't". |

---

## Majors

### M1 — velocity-map height model
**Decision:** tile-owned `surface_height`. Each tile module gains
`surface_height(...)` beside `emit`, sharing the same span arithmetic;
`TileImpl.surface_height_fn` carries it; `estimate_surface_height` becomes
registry dispatch; `register_tile` gains an optional `surface_height`.
`cross_ratio` folded into the height model.

**Why:** the three estimator bugs (M1/M2/M6) all came from `velocity_map` keeping
a second, hand-derived model of each tile's surface. Co-locating the emitter and
the height function is the structural defence; a point fix leaves the drift in
place. Also closes the extension half of V14.

**Cost:** public `register_tile` signature grows one optional kwarg. No behaviour
change for valid input. Rejected alternative: patch the three functions in place
and rely on a drift test.

### M2 — rough heightmap y-mirroring
**Decision:** flip the sampler, not the PNG — `v = 0.5 - local_y/tile_y`. Record
the PNG-row/hfield-row inversion in a comment.

**Why:** flipping the PNG would mirror every existing rough tile for every seed,
invalidating renders and anything trained against them, to fix a debugging
convenience. The estimator is the thing that is wrong.

**Cost:** none — emitted geometry bit-identical.

### M3 — `python -m` exit code
**Decision:** `sys.exit(main())` in `__main__.py`, plus a **subprocess** test that
actually spawns `python -m`. Exit-code *values* left alone; `--version` and the
unused `cmd_list(args)` deferred to the nit batch.

**Why:** a test that imports and calls `main()` passes on the broken code, so only
a spawned test is meaningful. Renumbering exit codes is churn with a
compatibility cost and no clear win.

**Cost:** `python -m` now returns non-zero on failure. Anything relying on it
returning 0 was relying on the bug. Fixes `_rebuild_myoassist.py`'s dead
`returncode` check as a side effect.

### M4 — flat-at-base contract
**Decision:** enforce it in `stairs`. Auto-fill becomes
`step_width = (long - peak)/(2n + 2)`, giving exactly one tread of flat margin
per end; inverted stairs emits a 4-sided base frame instead of two cross strips.
`gap` documented as the one deliberate exception.

**Why:** the measured audit (36 perimeter probes, all 9 tiles plus every
`inverted` variant) showed `stairs` is the *only* tile that violates it, plus
`rough` via M5's separate cause. `slope`, `pyramid_stairs` and the scatter tiles
all comply, including inverted. That narrowed the fix enough to make enforcing
cheaper than documenting exceptions. A 15 cm riser at the connector seam on the
default config is a trip hazard the docs deny exists.

**Cost:** stairs geometry changes — tread −14.3%, flight angle 25.2°→28.7° on 5 m
tiles; peak height (1.08 m) and plateau width unchanged. Visible in a single-tile
close-up, indistinguishable at terrain-figure scale. Affects 4 of 9 shipped
configs; `m2_demo`/`m3_demo` pass explicit `step_width` and are untouched. The
website's `assets/terrains/stairs.png` wants regenerating.

**Corrections to the original report made while scoping this:** inverted variants
do *not* leave the perimeter open (there is geometry; the edge sits one riser
down), and `gap` violates the contract too, which the report never flagged.

### M5 — rough hfield renormalization
**Decision (superseded):** correct both `origin` and `size[2]`.

**Decision (final):** **origin-only** correction —
`origin = base_top_z - vertical_relief * (h_edge - hmin)/span`.

**Why the change:** quantifying the first version showed it altered the tile's
*shape* — emitted excursion shrank 8.6% and peaks dropped 60 mm. Origin-only
achieves the same exact perimeter as a pure vertical translation, and keeps
`vertical_relief` meaning actual peak-to-trough excursion, which is what
`docs/tiles.md:59` already claims and the more useful reading for tuning
difficulty.

**Cost:** `relief_mode="centered"` (the default) shifts **−27 mm**; `"up"` and
`"down"` are unchanged because their edge value is already a data extreme. Shape
and relief identical.

### M6 — pyramid level truncation
**Decision:** guard the negative case, then floor — `level = 0` when
`edge_dist < outer_margin`, else
`min(n_steps, int((edge_dist - outer_margin) // step_width) + 1)`.

**Why:** `int()` truncates toward zero, so the entire flat outer margin was
promoted to level 1; the `max(0, ...)` sat outside the `+1` where it could not
help.

**Cost:** estimator only, no emitted geometry.

---

## New findings raised during the fix discussion

### N-X1 (REVISED) — seating: terrain exports the surface height

**Supersedes the original disposition** ("not fixed here, scoped as a myoassist
change"). Write scope amended: `myoassist` is in play and nothing critical is
deferred.

**Two corrections to the original finding, both from prototyping the fix:**

1. It is **not** grid-specific. `uniform random` (a single heightfield) is broken
   too — the model is flung far enough that there are no terrain contacts at all
   at a sane probe margin. The real split is **plane-based terrain works,
   everything with finite or heightfield geometry does not.** `flat` and `slope`
   escape because plane-mesh distance stays exact at any margin.
2. The one-line margin reduction I first proposed is **inadequate**. Measured
   across 9 terrains, `margin=20` fixes only 2 of the 6 broken cases; `grid
   stairs`, `flat_smoke_test`, `m4_demo` and `m5_random` stay wrong.

**Prototype results** (metric: tightest terrain-model gap at margin 0.05, where
MuJoCo distances are physical; target `-0.0050`):

```
terrain                today (m=50)     ray-cast    two-stage
uniform flat            -0.0050 OK    -0.0050 OK   -0.0050 OK
uniform slope 8deg      -0.0051 OK    -0.0083 OK   -0.0050 OK
uniform random              nan BAD   -0.0791 BAD      nan BAD
grid flat               -1.1394 BAD   -0.0050 OK   -0.0050 OK
grid stairs             -1.1388 BAD   -0.0050 OK   -0.0050 OK
flat_smoke_test         -0.3094 BAD   -0.0050 OK   -0.0050 OK
myoassist_base          -1.1388 BAD   -0.0050 OK   -0.0050 OK
m4_demo                     nan BAD   -0.0841 BAD      nan BAD
m5_random               -0.2670 BAD   -0.0050 OK   -0.0050 OK
```

Both prototypes were abandoned: they have myoassist re-deriving, by collision
probing, something the terrain package already knows exactly.

**Decision — export the height from `myoassist_terrains` and consume it in
`myoassist`.** Nearly free given M1's tile-owned `surface_height`.

On the terrains side:

- Promote the surface-height query to public API: **`surface_height_at(config, x, y)`**
  and **`max_surface_height_in(config, x, y, radius)`**, handling both config
  forms. Standalone functions; `build_terrain` keeps returning just an `MjSpec`
  (its return type is public and used by the siblings).
- **Cover the connector strip.** Today the query returns `0.0` for any position in
  the border region; it must return the connector's negotiated `match_mode`
  height, which the composer already computes.
- **Scatter tiles model their objects.** `discrete_obstacles`, `boulders` and
  `stepping_stones` replay their own seeded draws in `surface_height` and report
  the true top surface at `(x, y)`, not just `base_height`. This extends the M1
  decision, which had them returning the base slab. It matters concretely:
  `myoassist_base` spawns the model over `discrete_obstacles` with 15-35 cm
  obstacles, and a base-height answer would seat it interpenetrating one. It also
  makes the velocity map correct over those four tile types.

On the myoassist side:

- `_seat_dz_by_collision` is replaced for the composed-from-config path: measure
  the model's lowest foot vertex exactly from mesh vertices (no margin, no
  narrowphase), query the terrain height under the footprint, and set
  `dz = terrain_z - foot_z - penetration`.
- Keep a collision fallback for the `model_path` case, where there is no terrain
  config to query — with a sane margin, since the 50.0 value is the bug.

**Why this is the right shape:** it removes the magic constant, removes the
MuJoCo-version dependence (verified the failure is identical on 3.3.3, 3.4.0 and
3.11.0), puts the knowledge in the package that owns the geometry, and gives RL
and CO a documented way to ask "how high is the ground here" for any purpose,
not just seating.

**Demo:** `~/Work/nx1_demo` — three loadable MJCFs (`A_grid_flat_BROKEN`,
`B_uniform_flat_OK`, `C_grid_flat_FIXED`), `nx1_comparison.png`,
`nx1_pelvis_trajectory.png`, and a README with the measurement table and a
reproduction snippet. The broken model does not error: it starts buried at
`-0.64`, is shoved to `-0.055`, and stays there for the whole episode with its
torso inside the terrain slab.

### N-X2 — in-process rebuilds reuse a stale heightfield
**Decision:** content-address hfield PNG filenames
(`{terrain_name}_{tile}_{hash8}.png`, digest of the heightmap bytes) **and prune
superseded siblings on build**.

**Why:** MuJoCo caches decoded assets by path within a process, and the filename
was derived from `terrain_name` alone, so an in-process rebuild silently reused
the first build's heightfield. Verified: `hfield_data` identical across two
different seeds, correlating +1.00000 with the *previous* build's PNG and only
+0.712 with its own; separate processes and distinct names both behave correctly.
Content addressing makes a cache hit correct by construction; pruning stops
orphans accumulating in the user's project directory.

**Cost:** asset filenames change (`docs/project-layout.md:12` example). Zero
geometry change. Build now deletes superseded `{terrain_name}_{tile}_*.png` in
the library dir.

**Exposure:** safe on the CLI (one build per process), `_rebuild_myoassist.py`
(subprocesses), and `compose_env_model` without `export_path` (fresh `mkdtemp`).
Exposed: `compose_env_model` **with** `export_path` twice in one process, and any
in-process parameter sweep or RL curriculum rebuilding under one name.

---

## Moderate batch 1 — validation gaps

All six reject bad input earlier and with a better message. None changes
behaviour for a valid config.

| ID | Decision | Compatibility |
|---|---|---|
| V1 | Reject duplicate `(row, col)` in `TerrainConfig.__post_init__`. | Rejects configs that previously either crashed in MuJoCo (`repeated name`) or silently double-emitted overlapping tiles. Also guards `compose`, since `EnvSpec.validate()` calls this. |
| V2 | Validate `outer_margin` against `tile_size`, and require `> 0` when `inverted`, in `pyramid_stairs`. | Turns `size 1 must be positive in geom` into a tile-level message naming the parameter, matching every other tile's style. |
| V3 | Inset scatter placement by the **sampled radius**: `half_inner = tile/2 - edge_margin - max(size_range)`. | Boulder/obstacle positions move inward for a given seed, so those renders shift slightly. Rejected the alternative (raise an error) because it invalidates the shipped `boulders` defaults, whose `size_range` max of 0.60 already exceeds `edge_margin` 0.50. |
| V19 | Reject a `param_ranges` entry targeting a list-valued default, with a message saying list-valued params cannot be randomized. | Turns a deep `TypeError` into an actionable config error. Making them genuinely randomizable is a feature, deliberately out of scope. |
| V20 | Raise on `hi < lo` in the float sampling branch, matching the int branch. | Rejects configs that previously sampled `[hi, lo)` silently. |
| V21 | Reject a `terrain_name` that is not a bare filename. Implemented in `config.py` so the Python API is guarded too, not just the CLI. | Rejects names containing path separators or `..`. |

---

## Moderate batch 2 — silent-ignore gaps

| ID | Decision | Compatibility |
|---|---|---|
| V6 | Reject unrecognised top-level keys in **both** config forms, allowing `_`-prefixed keys through as comments (matching the `_comment` convention in `utils/render/*.json`). Error names the key and lists the valid set. Separately, validate tile `params` against `inspect.signature(emit_fn)` so a typo reports `tile 'flat' at (row=0, col=0): unknown param 'heght'; valid: height` instead of `TypeError: emit() got an unexpected keyword argument`. | Verified safe: zero extra top-level keys and zero extra tile params across all 13 shipped configs, and every `myoassist` call site uses schema keys only. The signature check also covers custom tiles. |
| V7 | Raise when `texture` is set and `palette_preset` is not `uniform`, instead of silently discarding it. | No shipped config combines them. Previously the block was dropped *and* its file never checked, so a typo'd path was silent in one mode and a hard `FileNotFoundError` in the other. |
| V8 | Unify with the uniform-terrain path: honour `palette["uniform"]` (or `"terrain"`) as a global tint in uniform mode, exactly as `_resolve_uniform_appearance` already does, and raise on per-type keys since they cannot apply to a single shared colour. | Removes the dead computation at `composer.py:711-718`. Makes the grid and uniform-terrain paths agree. |
| V9 | **Drop the `terrain_style.xml` colour read entirely.** Delete `_read_uniform_rgba_from_style`; `_UNIFORM_RGBA` becomes the single documented default, overridable per config via `palette`. | Feature removal, but the feature never fired through `compose` (temp assets dir), which is how nearly everyone reaches it. See the migration below. |

### V9 migration

Measured: the same config renders **two different colours** today depending on
where it is built, because the read resolves `output_dir.parent/terrain_style.xml`:

| config | via the render pipeline | in a user project |
|---|---|---|
| `base`, `base_tiled3x3`, `base_tiled5x5` | `0.792 0.996 1.0` (near-white, from `utils/render/terrain_style.xml`) | `0.31 0.663 0.667` (teal, from `utils/style/terrain_style.xml`) |
| `myoassist_base`, `myoassist_tiled` | `0.792 0.996 1.0` | `0.31 0.663 0.667` |
| the 8 `diverse`-preset configs | unaffected | unaffected |

Dropping the read pins all five to the `0.78` grey constant, which matches
neither. To keep appearance identical, each config gets an explicit `palette`
recording the colour it renders as today:

- `base.json`, `base_tiled3x3.json`, `base_tiled5x5.json` → `"palette": {"uniform": [0.792, 0.996, 1.0, 1.0]}` (these drive the checked-in renders)
- `myoassist_base.json`, `myoassist_tiled.json` → `"palette": {"uniform": [0.31, 0.663, 0.667, 1.0]}`

Nothing visibly changes, and the colour becomes explicit in the config instead of
implicit in a file's position relative to an output directory.

`terrain_mat` **stays** in both style files — `utils/render/terrain_config.xml:24`
uses it as the material on a real geom. Only the composer's read goes away.

Stale comments and docs to correct as part of this: `composer.py:56-58`,
`utils/style/terrain_style.xml:16-18`, `utils/configs/_rebuild_myoassist.py:29-30`,
`utils/render/_build_velocity_config.py:18`, `docs/concepts.md:38`,
`docs/utilities.md:49`, and `myoassist-web/modeling/terrains/index.md:62`.

---

## Moderate batch 3 — output path and CLI

V4 and V5 are one problem. The fix makes `cmd_preview`'s currently-false docstring
true rather than rewriting it.

| ID | Decision | Compatibility |
|---|---|---|
| V5 | Make the preview wrapper chain `../terrain_style.xml` when it exists, so the docstring's claim becomes real. Fall back to a minimal built-in headlight + skybox when absent, and add `<visual><global offwidth offheight/>` either way. | Path arithmetic verified: the wrapper is top-level in `<root>/terrain/`, so `../terrain_style.xml` resolves to `<root>/terrain_style.xml`, and the terrain's `../terrain/*.png` asset paths keep resolving. No material-name collisions (style declares `terrain_mat`/`matfloor`/`texfloor`; terrain declares `myoassist_mat_*`/`terrain_texfloor`). Preview stops rendering an unlit void and stops being capped at 640x480. |
| V4 | Keep `emit_xml_include` excluding `<visual>`. Rewrite the docstring to state it is a deliberate contract, not an oversight. No opt-in parameter. | With V5 fixed the haze loss is no longer user-visible: `compose` injects it from `to_xml()` (`compose.py:275`, `_inject_terrain_haze:180-192`), a user project gets it from `terrain_style.xml:34`, and preview now chains that same file. Rejected emitting it because a `<visual>` inside an include merges into the consuming model, and since `terrain_config.xml` includes the style *before* the terrain, a terrain-supplied `<rgba haze>` would silently override the user's own style. |

---

## Moderate batch 4 — infrastructure

| ID | Decision | Notes |
|---|---|---|
| V10 | Tag-triggered publish on `v*`; convert `test.yml` to `on: workflow_call` and require it as a gate in `publish.yml`; create `CHANGELOG.md`; unify on `python -m build` in both workflows; **remove `uv.lock`**. | Tag-triggering fixes the missing test gate, the missing release tags, and the accidental-republish 409 in one move. `python -m build` chosen over `uv build` because it is the PyPA standard and removes a third-party action from the job holding `id-token: write`; this diverges cosmetically from `assist_sim`, same artifacts. |
| | `uv.lock` removal verified safe | No uv workspace in any sibling; nothing references this lock. Family state: `myo_sim` commits a lock *and* runs `uv sync --dev`; `assist_sim` has no lock and uses `uv build`; `myoassist` has `[tool.uv]` but no lock. This repo was the worst combination — a lock nothing consumed. Removal matches `assist_sim`. |
| V11 | Add `windows-latest` on one Python leg; add **Python 3.13** to the matrix and to the classifier list. | Verified in an isolated 3.13.5 venv: `pip install -e ".[dev]"` resolves and **84 tests pass**. The install pulled **mujoco 3.11.0**, far newer than the 3.3.3/3.4.0 previously tested, so the unbounded `mujoco>=3.3.3` range is currently sound. Windows matters because the code carries three `.replace("\\", "/")` workarounds CI has never exercised on the platform they exist for. |
| V12 | Correct `docs/utilities.md:49-50` to stop documenting `mesh/` and `terrain_config.xml` as repo contents; mark which render scripts need local-only assets (`render_ensemble.py`, any `ensemble_*.json`) versus which run from a clean clone (`render_velocity_map.py`, `render_terrain_check.py --config terrain5x5_velocity.json`, both verified). Commit no binaries. | Rejected vendoring the fixtures: `26muscle_3D/*.xml` and the STL meshes are myoLeg assets belonging to `assist_sim`/`myo_sim`, and duplicating them here would fork them. Repointing the ensemble configs at installed `assist_sim` paths is the better long-term fix but is a feature, not a correction. |
| V13 | `.gitignore`: replace the two hard-coded `*_terrain_assets` lines with `utils/render/*_terrain_assets/`, and add `utils/render/tmp*.xml` (N18's temp-scene leak). | The two scripts derive the directory from `scene_name`, so any other scene leaked an untracked dir — reproduced by running the documented `render_terrain_check.py` command. |

### Cross-version validation of the agreed fixes

Every measurement the Major fixes depend on is identical on **mujoco 3.11.0 /
py3.13** and **mujoco 3.4.0 / 3.3.3 / py3.12**:

| check | 3.3.3 / 3.4.0 | 3.11.0 |
|---|---|---|
| M5 `rough` perimeter, `centered` | +0.0328 | +0.0328 |
| M5 `rough` perimeter, `up` / `down` | +0.0000 | +0.0000 |
| M2 corr(hfield, png) as-is / y-flipped | −0.32766 / +1.00000 | −0.32766 / +1.00000 |
| M4 `stairs` perimeter, auto `step_width` | +0.1500 | +0.1500 |

So the fixes hold across the whole supported range rather than being tuned to one
MuJoCo version.

---

## Moderate batch 5 — leftovers

| ID | Decision | Notes |
|---|---|---|
| V14 | Add `TileImpl.default_speed_scale` (populated for the nine built-ins) and `register_tile(speed_scale=...)`. `DEFAULT_SPEED_SCALE` stays a public symbol but becomes a mapping derived from the registry. | Mirrors M1: per-tile knowledge lives on the tile, so it cannot drift from what it describes. A custom tile then works with no velocity-map edit. Closes the other half of V14. |
| V15 | Convert caller-input asserts in `velocity_map.py` / `velocity_arrows.py` to `ValueError`. Keep genuine internal invariants as asserts, flagged in the diff so the distinction is deliberate. | Under `python -O` the input checks currently vanish entirely, taking the `mode` / `tile_radial_mode` spelling validation with them. |
| V16 | Explicit type check in `generate_velocity_map`: a `UniformTerrainConfig` raises a clear `ValueError`, plus a line in `docs/velocity-maps.md`. | Replaces `AttributeError: 'UniformTerrainConfig' object has no attribute 'grid'`. |
| V17 | Special-case `count == 1` in `_sample_offsets` to return `[0.0]`. Margin formula otherwise unchanged. | `np.linspace(a, b, 1)` returns the low endpoint, so a single sample sat at -32% of the tile. Verified neither existing `samples_per_tile=1` test breaks: one asserts a goalward direction (true at centre), the other an axis-locked direction that is position-independent. Rejected making the margin density-independent, which would move every sample at every density and change all velocity renders. |
| V18 | `add_velocity_overlay` raises a clear `ValueError` on an empty sample list rather than dying in `min()`. | Chosen over a silent no-op: `generate_velocity_map` always returns at least one sample for a valid config, so an empty list is a caller bug. |

---

## Documentation batch

### Already resolved by code decisions (not doc edits)

- **M4 / M5** make the boundary-contract text true as written. `docs/concepts.md:25-29` and the website's `index.md:51-53` / `tile-types.md:12-14` need only a `gap` exception added.
- **V9** deletes the `terrain_style.xml` read, so D9's false claim goes with the code. `docs/concepts.md:38` and website `index.md:62` get rewritten around `palette`.
- **V6 / V7 / V8 / V19 / V20 / V21** add real validation, so `docs/configuration.md` gains a constraints section.
- **N-X2** changes the asset filename pattern → `docs/project-layout.md:12`.
- **D5**, **D20** are already fixed on the website; only the local copies need them.

### Decisions

| ID | Decision |
|---|---|
| D10 | **`palette_preset: "custom"` gets real meaning: a strict palette.** It requires an entry for every placed tile type and errors if one is missing; `diverse` keeps defaults with optional overrides. Chosen over documenting it as an alias because the names already imply the distinction and it makes final-render configs self-checking. Safe: no shipped config uses `custom`. |
| D1 | **Local = field reference, website = narrative.** `docs/configuration.md` gains a terse field table for the uniform form (name, type, default, constraint) covering `deg`, `amplitude`, `period`, `seed`, `extent`, `resolution`, `safe_zone_radius`, `base_depth`, `terrain_name`, `palette`, `texture` — none of which is documented anywhere today. The website gets prose, examples and figures. Different content, so there is no prose to drift. |
| D22 | **Apply the STE pass locally too** (14 em dashes, British spellings across README and 3 doc files), so shared passages stop diverging on style as well as fact. |
| Doc drift | **Generate the tile catalog tables from the registry.** A script emits them into `docs/tiles.md` between markers; a test runs it in `--check` mode so CI fails if a default changes without regenerating. Descriptions come from a new `PARAM_DOCS: dict[str, str]` per tile module (same co-location logic as M1), and `register_tile` accepts it so custom tiles document themselves. The website's tables are wrapped in per-tile figure divs, so regenerating them there is a manual paste — noted in the website changelist. |
| Shared factual errors | Fix locally and add to the website changelist: **D2** (radians), **D3** (density as area fraction, 2 rows), **D4** (boulders as half-spheres with a diameter range), **D6** (rough relief circular + taper-to-0), plus the `step_width` description which M4 changes. |
| Local-only fixes | **D11** `python-api.md` (4 errors), **D12** `development.md`, **D13** `utilities.md` (4 errors incl. V12), **D14** `myoassGreist_terrains` typo + `26muscle_3D` vs `models/`, **D15**, **D16** (`gap` vs `stairs` axis semantics), **D17** (milestone codes in a user-facing error), **D18**, **D21**, and code-comment fixes **D7** (`invert_relief` does not exist) and **D8** (slope normal sign). |
| D19 | **Code fix, not a doc fix:** align `stairs.emit`'s `peak_width` signature default to `0.40` so it stops disagreeing with `DEFAULT_PARAMS`. |

---

## Nits batch

| Disposition | Items |
|---|---|
| Fix | **N1**, **N3**, **N4**, **N6** (dead params, duplicated texture parser); **N7**, **N12**, **N13**, **N19**, **N22** (comment/docstring corrections); **N8**, **N11** (duplicate branches, materials emitted for every registry entry); **N9** (below); **N15** (missing `__main__` guards); **N16** (assert the 3x3 base shape); **N17** (import from the package, not `render_ensemble` privates) |
| Remove | **N5** — `TileEmitResult.boundary_heights` has never been read, and M4's decision means nothing will. A future per-side contract can reintroduce it with the design it actually needs. |
| Moot | **N2** — `_read_uniform_rgba_from_style` is deleted by V9, taking its unused parameter with it. |
| Won't fix, documented | **N10** (quadratic smoothing, measured ~1.0 s at 8100 samples — noted, not rewritten); **N14** (two XML-construction styles; unifying is a rewrite with no correctness payoff); **N18** (the temp scene must sit beside the config for relative asset resolution — V13's gitignore entry covers the leak) |
| N20 | **Add `--root` and `--version`.** `--root` makes `build`/`list`/`preview` usable from anywhere and complements the existing env var; `--version` exposes the already-public `__version__`. |
| N21 | **Add `I` and `ARG` to the ruff rule set**, drop the vestigial `"external"` exclude. `ARG` becomes enforceable because V6's signature inspection lets the composer pass `output_dir`/`terrain_name` only to tiles that declare them, legitimately removing 14 unused args instead of suppressing the warning. Reformats imports across 23 files (mechanical). |

### N9 / N10 measured

Warm-cache timings on `base_tiled5x5` (15x15), `samples_per_tile=6`, 8100 samples:

```
surface_height_at        143.2 us/call, of which compute_cell_layouts = 114.0 us (80%)
  called 5x per sample -> 40,500 calls = 5.8 s, of which 4.6 s is pure layout rebuilding
_smooth_sample_speeds    ~1.0 s total
```

So **N9 is roughly 60% of the velocity render's runtime** and is a clean hoist with no
behaviour change; N10 is not currently the bottleneck. (A first measurement
attributing 63% to smoothing was confounded by the `_rough_heightmap` LRU cache
being cold on the first run.)

---

## Tests batch

| ID | Decision |
|---|---|
| T1 | CLI + `paths.py` coverage, including a **subprocess** test for M3 (an in-process call to `main()` passes on the broken code, so only a spawned test is meaningful). |
| T2 / T3 | The ray-cast fixture: assert every tile's perimeter sits at `base_height` at defaults, and assert every `surface_height` matches the compiled geometry. This is the durable guard behind M1, M2, M4, M5, M6 and V3, and it is written **before** those fixes so they are proven rather than asserted. |
| T4 | Fail on an empty `parametrize` list instead of passing vacuously. |
| T5 | Switch to the public `config_from_dict` and give it coverage. |
| T6-T9 | `compute_cell_layouts`; `emit_xml_include`'s prefix parameters; `border.match_mode` connector heights; the uniform terrain XML path. |
| T10-T12 | Correct the three misleading test comments and the last-sample-wins assertion. |
| T13 | **Coverage reported, no failing threshold.** A `[tool.coverage]` config plus the report in CI. `cli.py` and `paths.py` go from 0% to covered this pass, so the trend is the useful signal; an arbitrary floor mainly blocks the next contributor. |
| T14 | `==` instead of `issubset` so a stray registry entry is caught. |
| New | Regression tests for N-X2 (stale in-process asset), V1, V2, V6, V16, V17, V18, V19, V20, V21, and the generated-doc `--check`. |

---

## S5 — compose-cache compatibility (added requirement)

**Requirement:** terrain outputs must stay compatible with the myoassist/assist_sim
environment cache (`ctrl_optim-testing`, commits `9dac392` + `701af71`) so training
speed is not hindered by terrain/env/model composition.

**Measured value of the cache:** cache hit **0.018-0.028 s** vs **1.42-1.45 s** cold,
about 68x. Worth protecting.

**Already handled upstream.** `701af71` folds a
`terrains@{_package_token(myoassist_terrains)}` token (version + newest source
mtime) into the cache key, so this review's geometry changes (M4, M5, V3) will
correctly invalidate existing entries. No action needed.

**Found broken, reproduced.** `_compose_env_model_cached`'s docstring assumes "no
supported terrain type writes asset files". True for the uniform forms, false for
any grid terrain containing `rough`, which writes a PNG heightmap. On a warm cache
in a fresh process the entry references the *previous* process's temp dir, which
was removed by compose's `atexit` rmtree:

```
[uniform_random] compose=0.022s  png_refs=0  missing=0  -> OK
[grid_rough    ] compose=0.021s  png_refs=1  missing=1  -> FAILED:
    Error opening file '.../Temp/myoassist_terrain_kd6od4kw/cr_rough_r0c0.png'
```

Currently masked because N-X1 makes grid terrains unusable anyway; it becomes the
next blocker the moment N-X1 lands.

**Decision — give compose a stable asset directory when caching.** Two lines: use
`cache_dir / "terrain_assets"` instead of `tempfile.mkdtemp(...)`, and skip the
`atexit` rmtree for it. Verified across three processes:

```
proc 1 (cold)               compose=1.452s  asset written   load OK
proc 2 (warm, new process)  compose=0.027s  asset present   load OK
proc 3 (warm, new process)  compose=0.018s  asset present   load OK
```

**Rejected: baking rough heightfields into the spec** via `hfield.userdata` (as the
uniform path does), which would make the "single file" assumption universally true.
Measured XML cost:

```
tiles  res    XML size   to_xml   from_xml_string
    1   64     0.04 MB   0.005s   0.002s
    9  256     5.28 MB   0.616s   0.080s
   32  256    18.76 MB   2.220s   0.279s
```

At the default `grid_resolution=256` a large terrain costs 18.8 MB and 2.2 s to
serialise, which defeats a 0.02 s cache hit. Lowering the default was rejected
separately: 256 over an 8 m tile is 3.1 cm cells, and foot-scale contact needs it.

**Consequent refinement to N-X2.** Content-addressed filenames are now *required*,
not cosmetic: a shared persistent asset dir means two configs with the same
`terrain_name` would otherwise collide there, and MuJoCo's in-process path cache
would serve the wrong heightfield. Conversely **pruning becomes opt-in** — it must
run only on the explicit CLI `build` into a project's terrain library, never in a
compose asset dir, where deleting a "superseded" PNG could break another live cache
entry.

**Consequent constraint on the N-X1 API.** `surface_height_at` is called on the
compose path, so it must stay cheap: memoize the scatter tiles' RNG replay per
(seed, params) alongside the existing `_rough_heightmap` LRU cache, and apply N9's
layout hoist. It is only reached on a cache miss, so the bar is "not slow", not
"microseconds".

**Expected side benefit.** N-X1's fix removes a 50 m-margin collision broadphase
over every terrain geom (~19k on a 15x15 grid), so cold compose for grid terrains
should get *faster*, not slower. To be measured during implementation.

---

## Still open (deliberately deferred)

- **`myoassist-web` changelist** — the 7 shared factual errors, the website-only `configuration.md:13-14` claim, a uniform-terrain narrative page, the reworded `terrain_mat` and boundary-contract passages, and regenerated `assets/terrains/stairs.png` + tile tables. Scoped, not written (per S1).
- **`myoassist/docs/reinforcement-learning/03_terrain-types.md`** — the third copy. Recommend retiring once the website's uniform page lands.
## Follow-through

Three decisions change emitted geometry: M4 (stairs treads −14.3%), M5
(`rough` centered −27 mm), V3 (scatter positions inset). One changes asset
filenames (N-X2). On implementation: rebuild the shipped configs, regenerate the
affected renders, and record each in a `CHANGELOG` (which the repo lacks — V10).

---

## Implementation status

All batches implemented. Status: **complete**, pending review of the two branches.

- `myoassist.terrains` branch `review-1-remediation`, 11 commits off `main`.
- `myoassist` branch `ctrl_optim-testing`, 1 commit (seating + compose cache).
- `myoassist-web`: not written. Scoped in `WEBSITE_CHANGELIST.md`.

### Verification

| Check | Result |
|---|---|
| Test count | 84 -> 183 (1 skipped: `gap`'s documented perimeter exception) |
| Coverage | 84% overall; `cli.py` and `paths.py` 0% -> 100%; `velocity_arrows.py` 0% -> covered |
| `ruff check` / `ruff format --check` | clean, with `I` and `ARG` newly enabled |
| mujoco 3.3.3 / 3.4.0 / 3.11.0 | 183 passed on each |
| Python 3.12 / 3.13 | 183 passed on each |
| Shipped configs | all 13 build, compile, and keep their exact colours |
| Documented render commands | both run from a clean clone |
| Seating, 11 terrain types through `compose` | all settle; root moves <= 2 mm in the first 20 ms |
| Compose cache, tiled terrain across 3 processes | loads on a warm cache (was a hard failure) |

### Things that turned out differently from the plan

Recorded because the decisions above were made on the earlier understanding.

1. **The predicted seating speedup was wrong.** Asking the terrain for its height
   instead of collision-probing was expected to be faster, since it drops a
   broadphase pass over every terrain geom. The first implementation was 3-19x
   *slower* (1219 ms against 64 ms on a single tile) because it queried every mesh
   vertex. A two-stage narrow-then-refine brought it to parity (77.8 ms against
   76.7 ms); both are dominated by the `from_xml_string` compile each performs
   anyway. No speedup, no regression.

2. **MuJoCo does not interpolate heightfield cells bilinearly.** It splits each cell
   across the main diagonal. Found only because a residual error would not go away:
   bilinear was off by up to 30 mm between nodes, main-diagonal triangle
   interpolation is exact at 400/400 ray-cast probes, and the anti-diagonal is worse
   than bilinear, which rules out coincidence. This mattered directly: the error set
   how deep a model was seated. `hfield.py` now holds the sampler both heightfield
   users go through.

3. **Flipping a sample coordinate is not the same as flipping the grid.** `rough`
   needs the PNG-to-hfield row inversion, and negating the row coordinate turns
   MuJoCo's main diagonal into the anti-diagonal, so the wrong triangle was
   interpolated. Flipping the grid once, then working in hfield coordinates, took the
   residual from 39 mm to 0.000000 m.

4. **Two test methodologies were wrong before the code was.** `mj_ray` degenerates on
   heightfield triangle edges and reports the base plane instead of the surface, and
   the first probe grid used the same offset on both axes, putting every point on the
   `x == y` diagonal. Both would have been "fixed" by loosening tolerances to roughly
   a full relief, which would have hidden real error. Probes are now nudged
   differently per axis, and the tolerances are tight (1 mm for tiles, 1 um at
   heightfield nodes, which is float32 storage noise).

5. **`ARG` needed no per-file exemption for the tiles.** The plan assumed tile
   `surface_height` functions would need one for their uniform signature. Declaring
   only the parameters each tile uses and absorbing the rest with `**_` removed the
   need, and exposed four genuinely dead `emit` parameters in the process.

6. **The STE em-dash convention broke an XML file.** Replacing em dashes with `--`
   is not what STE asks for (it wants plain punctuation), and `--` is illegal inside
   an XML comment, which made `utils/style/terrain_style.xml` unparseable and broke
   the render scripts that chain it. Fixed with a semicolon. A test guarding this was
   drafted and then dropped as over-engineering for a self-inflicted problem.

### Scope changes made during implementation

- **`flat_smoke_test.json` spawns the model at a 4-way corner** where tiles differ by
  0.5 m, so no placement both touches the ground and avoids interpenetration. The
  seating correctly lifts to clear the step. That is a poor spawn point rather than a
  defect, and changing the config was left out of this pass.
- **`camera_convert.py` gained the reverse direction** rather than having its
  documentation corrected. `docs/utilities.md` claimed the conversion was
  bidirectional; implementing the missing half was smaller than the alternative and
  made the claim true.
- **`_make_tiled.py` was restructured** for the `__main__` guard, and verified to
  regenerate `myoassist_tiled.json`'s tiles byte-identically.
