# Utilities and example configs

The `utils/` tree ships ready-to-use JSON configs, user-side style and asset
templates, and standalone helper scripts.

## Example configs (`utils/configs/`)

Every one of these is built and compiled by `tests/test_examples.py`, so they cannot
drift out of step with the package.

| Path | What it is | Tile types |
|------|------------|------------|
| `flat_smoke_test.json` | Minimum-viable 2x2 flat terrain. Use it to verify a fresh install. | `flat` |
| `m2_demo.json` | 3x3 mixed demo. | `flat`, `slope`, `stairs` |
| `m3_demo.json` | 3x3 mixed demo, adds the heightfield tile. | + `rough` |
| `m4_demo.json` | 3x3 with every tile type, one per cell. | all nine |
| `m4b_relief.json` | 2x3 relief comparison. | `slope`, `stairs`, `pyramid_stairs` |
| `m5_mixed.json` | 3x3, one fixed cell and the rest randomized. | randomized |
| `m5_random.json` | 4x4, fully randomized. | randomized |
| `rough_only.json` | Single 12 m `rough` tile, for hfield asset emission. | `rough` |
| `myoassist_base.json` | 3x3 base terrain, 8 m tiles, concrete texture. | seven of nine (no `flat`, no `gap`) |
| `myoassist_tiled.json` | 9x9 tiling of the base, per-block rotations from `_make_tiled.py`. | as above |
| `base.json` | 3x3 base block, 5 m tiles, drives the render pipeline. | as above |
| `base_tiled3x3.json` | 9x9 (3x3 grid of `base` blocks). The ensemble/velocity render terrain. | as above |
| `base_tiled5x5.json` | 15x15 (`base` grown by three tile-rings); the center matches `base_tiled3x3`. | as above |

**`terrain_name` is not the file name.** `set-active` takes the `terrain_name`
inside the config, which for `myoassist_tiled.json` is `myoassist_base_tiled3x3`,
and for `base_tiled3x3.json` is `base_tiled3x3`. Run `myoassist-terrains list` to
see what is actually in a library.

## Config helpers (`utils/configs/`, `_`-prefixed)

| Path | What it is |
|------|------------|
| `_make_tiled.py <base.json> <out.json> [seed]` | Derive a 9x9 tiled config from a 3x3 base, with random per-block rotations and per-copy `seed` offsets. Requires a 3x3 base. |
| `_make_tiled_rings.py` | Grow the 9x9 outward by three rings to 15x15, preserving the center exactly. |
| `_rebuild_myoassist.py` | Rebuild `myoassist_base` + `myoassist_tiled` in one command, after editing the base JSON. |

## Documentation helpers (`utils/docs/`)

| Path | What it is |
|------|------------|
| `_gen_tile_catalog.py [--check]` | Regenerate the tile tables in `docs/tiles.md` from the registry. `--check` fails if they are stale, which a test runs. |

## User-side style and asset templates (`utils/style/`)

Copy these into a project to get the layout described in
[Project layout](project-layout.md).

| Path | What it is |
|------|------------|
| `terrain_config.xml` | Template active-terrain pointer, chaining the style then the active terrain. |
| `terrain_style.xml` | Template style include: skybox, fog, lights, `matfloor`, `terrain_mat`. |
| `terrain/default.xml` | Shipped flat-ground terrain the pointer targets out of the box; `set-active default` restores it. |
| `CONCRETE.png` | Sample concrete texture used by the base configs. |

`terrain_mat` is the material the shipped `default.xml` and the render-side pointer
reference. The generated-terrain `uniform` palette no longer reads its rgba: set the
color explicitly with `palette: {"uniform": [r, g, b, a]}` instead, because the old
read only fired when a style file happened to sit one level above the output
directory, so the same config produced different colors depending on how it was
built.

## Render tooling (`utils/render/`, needs the `[render]` extra)

**Some of these need model and mesh assets that are not in the repository.**
`26muscle_3D/`, `mesh/` and `utils/render/terrain_config.xml` are gitignored: they
are myoLeg assets belonging to `assist_sim` / `myo_sim`, and vendoring copies here
would fork them. The table says which scripts run from a clean clone.

| Path | What it is | Clean clone? |
|------|------------|--------------|
| `render_velocity_map.py` | Terrain-only velocity-arrow overlay from a terrain config + start/goal. | yes |
| `render_terrain_check.py` | Terrain (+ optional `--arrows`) with no models; free or fixed camera; `--emit-xml` writes a viewer-ready scene. | yes, with `terrain5x5_velocity.json` |
| `render_ensemble.py` | Compose multiple models on a shared terrain and render from one or more cameras. | no, needs the model assets |
| `_build_ensemble_config.py` | Validate per-variant qpos lists and emit a ready-to-render ensemble JSON. | no |
| `_build_velocity_config.py` | Build the full ensemble render configs. | no |
| `camera_convert.py` | Convert a MuJoCo camera between XML and the `pos`/`xyaxes` JSON used in ensemble configs, in either direction. | yes |
| `terrain5x5_velocity.json` | 15x15 terrain + velocity settings for `render_terrain_check.py`. References only tracked paths. | yes |
| `ensemble_*.json` | Ensemble render configs. All reference `26muscle_3D/myoLeg26_*.xml`. | no |
| `terrain5x5_viewer.xml` | An emitted viewer scene, kept as an example of `--emit-xml` output. | yes |
| `terrain_style.xml` | Render-side style copy, so the render scenes are lit like the figures. | yes |

Two commands that work from a clean clone:

```bash
python utils/render/render_velocity_map.py \
    --terrain-config utils/configs/myoassist_base.json \
    --start -10 -10 0 --goal 10 10 0

python utils/render/render_terrain_check.py \
    --config utils/render/terrain5x5_velocity.json \
    --arrows --free --elevation -90 --distance 130
```

Both write into gitignored output directories (`utils/render/images/`,
`utils/render/velocity_map/`, `utils/render/<scene>_terrain_assets/`).
