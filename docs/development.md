# Development

```bash
pip install -e ".[dev]"

pytest                                              # the suite
pytest --cov=myoassist_terrains --cov-report=term-missing
ruff check . && ruff format --check .               # both, as CI runs them

python utils/docs/_gen_tile_catalog.py              # regenerate the tile catalog
```

## What the suite covers

| File | Covers |
|---|---|
| `test_surface_contract.py` | Ray-casts the compiled model for every tile and every `inverted` variant: the flat-at-base boundary contract, and that each tile's `surface_height` matches the geometry its `emit` placed. |
| `test_surface_queries.py` | `surface_height_at` / `max_surface_height_in` against ray-cast truth, over both config forms, including connector strips. |
| `test_validation.py` | The configs that should be rejected: unknown keys, duplicate cells, degenerate parameters, discarded settings, impossible randomization specs. |
| `test_cli.py` | `build` / `set-active` / `list` / `preview`, exit codes through both invocations, and project-root discovery. |
| `test_composer_geometry.py` | Cell layout, connector heights per `match_mode`, asset path prefixes, and what the emitted include does and does not carry. |
| `test_composer.py`, `test_tiles.py`, `test_uniform.py` | Build-and-compile coverage per tile and per uniform terrain form. |
| `test_velocity_map.py`, `test_velocity_arrows.py` | Sampling, direction modes, and the arrow overlay. |
| `test_config.py`, `test_registry.py` | Schema validation and the tile registry, including the `surface_height` / `speed_scale` hooks. |
| `test_examples.py` | Every shipped config builds and compiles, and the generated tile catalog is not stale. |

## Two conventions worth knowing before you change a tile

**`emit` and `surface_height` must agree.** They are two views of the same geometry
and they live side by side in the tile module, sharing the same span arithmetic. The
velocity map used to keep its own copy of every tile's surface, and it was wrong for
four of the nine types. `test_surface_contract.py` holds them together by measuring
the compiled model, so a change to one that does not match the other fails there
rather than silently misplacing arrows or seating a model inside the ground.

**The tile catalog is generated.** `docs/tiles.md`'s tables come from each module's
`PARAM_DOCS`, `DEFAULT_PARAMS` and `PARAM_RANGES`. Add a parameter and you add its
description in the same file; a test fails if the committed catalog is stale.

## Testing across versions

The package supports `mujoco>=3.3.3` and Python `>=3.10`, and several of the fixes
in this codebase depend on specific MuJoCo behavior (heightfield renormalization,
cell triangulation). Those were verified identical on mujoco 3.3.3, 3.4.0 and 3.11.0,
and on Python 3.12 and 3.13. CI runs 3.10 through 3.13 on Linux plus one Windows
leg, which matters because the package carries three Windows-only path workarounds.
