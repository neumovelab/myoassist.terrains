# Code review — `docs-restructure` (D4 public-API refactor + D3 velocity-map docs + README→`docs/` split)

## Summary

`git diff main...docs-restructure` does three things: (1) **D4** promotes three
composer internals to public API — `_CellLayout`→`CellLayout`,
`_compute_cell_layouts`→`compute_cell_layouts`, `_resolve_tiles`→`resolve_tiles`
— so `velocity_map` no longer imports private (`_`-prefixed) symbols from
`composer`; (2) **D3** adds `docs/velocity-maps.md` documenting the (already-on-`main`)
velocity-map subsystem; (3) splits the 435-line `README.md` into a short landing
page plus ten `docs/*.md` files. The velocity-map subsystem code itself is on
`main` and out of scope (read for context only).

The D4 change is small, correct, and well-executed. The rename is backwards-safe
(the old names were private; both internal call sites — `composer.build_terrain`
and `velocity_map`'s three helpers — were updated, and a repo-wide grep finds no
lingering references to the old names). Naming is consistent with the package
(`build_terrain`, `emit_xml_include`, `load_config`; dataclasses `TileEmitResult`,
`VelocitySample` → `CellLayout`). The new module-path-only public surface
(`myoassist_terrains.composer.X`, not re-exported at top level) follows the
existing precedent set by `emit_xml_include`. Docstrings and type hints on the
newly-public symbols are complete, and `CellLayout` exposes only plain layout data
(`row`, `col`, `center_x`, `center_y`) — no private state leaked. Docs were
spot-checked against code (tile parameter tables for `flat`/`stairs`/`rough`,
CLI subcommands + `--activate`, console-script name, `requires-python`,
`generate_velocity_map`/`add_velocity_overlay`/`surface_height_at` signatures,
`DEFAULT_SPEED_SCALE`, `BASELINE_Z = -2.0`, all referenced `utils/**` paths) and
are accurate; all ten README→`docs/` links resolve and every removed README
section maps to a new doc file with nothing dropped.

No blockers or majors found.

## Findings

### Blocker
None.

### Major
None.

### Minor

**1. `resolve_tiles` is documented as returning row-major order, but only sorts when `randomization` is set.**
- `src/myoassist_terrains/composer.py:262` (docstring: "Returns a flat list of TileConfig in row-major order") and `docs/python-api.md:30` ("Resolve explicit + randomized `tiles` into a flat **row-major** `list[TileConfig]`").
- The `out.sort(key=lambda t: (t.row, t.col))` runs only in the randomization branch (`composer.py:300`). When `config.randomization is None`, the function returns early at `composer.py:268` with `out = list(config.tiles)` — i.e. in the user's config order. `load_config`/`TerrainConfig.__post_init__` (`config.py:123-143`) validate but never sort `tiles`, so a config listing tiles out of `(row, col)` order yields a non-row-major result.
- Why it matters: now that `resolve_tiles` is a *documented public contract*, a downstream consumer that trusts the "row-major" promise can get differently-ordered output for the no-randomization case. (No current in-repo consumer depends on order — `build_terrain`, `generate_velocity_map`, and `surface_height_at` all index by `(tile.row, tile.col)` — so this is a doc/contract-accuracy issue, not a live bug.)
- Suggested fix: make the promise true by sorting unconditionally (move the `out.sort(...)` so it also covers the early-return path), OR soften both the docstring and the `python-api.md` row to "row-major when randomization fills cells; otherwise in config order."

### Nit

**2. Two "public API" declarations describe different surfaces.**
- `src/myoassist_terrains/__init__.py:3-6` calls the "Public API surface (stable for v1)" exactly `build_terrain`, `register_tile`, and the CLI; the new `docs/python-api.md:22-35` presents a broader "Stable public surface" table that includes the newly-public `composer.resolve_tiles` / `composer.compute_cell_layouts` (and pre-existing `composer.emit_xml_include`, `config.load_config`, `tiles.REGISTRY`, `paths.find_terrain_root`, the velocity functions).
- Why it matters: a reader comparing the two could be unsure what is actually "stable." This is a two-tier convention (top-level `__all__` re-exports vs. module-path publics), which is reasonable, but it is implicit.
- Suggested fix: add a one-line note to the `__init__.py` docstring (or the `python-api.md` intro) that the top-level `__all__` is the convenience surface while additional stable symbols live under their module paths. `__init__.py` is unchanged by this branch, so this is optional.

## Open questions

- **Cross-repo use of the old private names.** The three renamed symbols were `_`-prefixed (private), so external callers should not have depended on them, and there is no back-compat alias. I could not verify whether a *sibling* repo (e.g. the `myoassist` main repo or `assist_sim`) imported `_compute_cell_layouts`/`_resolve_tiles` from this package — that's outside this diff. If any did, the rename would break the import; but relying on a private symbol would have been the caller's risk.
- **Top-level re-export.** Should `CellLayout` / `compute_cell_layouts` / `resolve_tiles` also be exported from `myoassist_terrains` (added to `__init__.__all__`) for discoverability, or is module-path access (matching `emit_xml_include`) the deliberate convention? The current diff chose the latter, which is internally consistent; flagging only in case top-level export was intended.
