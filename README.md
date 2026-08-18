# myoassist.terrains

**Modular procedural terrain generator for MuJoCo, designed to be used by [MyoAssist](https://github.com/neumovelab/myoassist) and other musculoskeletal-simulation projects within [MyoSuite](https://myosuite.readthedocs.io/en/latest/).**

`myoassist_terrains` turns a small JSON description into a ready-to-include MuJoCo
MJCF fragment. Two kinds of terrain are supported:

- a **uniform** surface: one plane or one heightfield (`flat`, `slope`, `random`,
  `sinusoidal`), suited to steady-state locomotion;
- a **grid**: a tiled course built from nine tile types, with explicit per-cell
  placement, weighted-random sampling, parametric variation of every tile, and a
  shared texture for uniform-palette renders.

It also answers where the ground is. `surface_height_at(config, x, y)` reports the
walkable surface height from the config alone, so a consumer placing something on
the terrain does not have to collision-probe a compiled model for it.

```
┌──────────────────────────────────────────────────────────────────┐
│  JSON config  ──►  build_terrain()  ──►  MjSpec  ──►  XML include│
│                       (Python API)          (compose)    (CLI)   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Getting started

### Installation

```bash
git clone https://github.com/neumovelab/myoassist.terrains.git
cd myoassist.terrains
pip install -e .

# Optional extras
pip install -e ".[render]"   # adds mediapy for ensemble renders
pip install -e ".[dev]"      # adds pytest and ruff
```

Requires Python `>=3.10` and `mujoco>=3.3.3`.

### Quick start

The shortest config is a uniform terrain:

```json
{ "terrain": "slope", "terrain_name": "gentle_climb", "deg": 8.0 }
```

A tiled course names its cells:

```json
{
  "terrain_name": "first_terrain",
  "grid":   { "rows": 2, "cols": 2, "tile_size": [10.0, 10.0] },
  "border": { "width": 0.5, "match_mode": "min" },
  "palette_preset": "diverse",
  "tiles": [
    { "row": 0, "col": 0, "type": "flat",   "params": { "height": 0.0 } },
    { "row": 0, "col": 1, "type": "stairs", "params": { "n_steps": 6, "step_height": 0.18 } },
    { "row": 1, "col": 0, "type": "slope",  "params": { "angle_deg": 18.0 } },
    { "row": 1, "col": 1, "type": "rough",  "params": { "seed": 42, "vertical_relief": 0.8 } }
  ]
}
```

Build it from a project that contains a `terrain_config.xml` pointer:

```bash
cd my_user_project        # contains terrain_config.xml + terrain_style.xml
myoassist-terrains build path/to/first_terrain.json --activate
```

The CLI writes `terrain/first_terrain.xml` into the project and, with `--activate`,
updates the `<include file="terrain/first_terrain.xml"/>` line in
`terrain_config.xml`. Any model that includes `terrain_config.xml` then sees the new
terrain. Use `--root <dir>` to build into a project from elsewhere.

Preview it without a user model:

```bash
myoassist-terrains preview first_terrain
python -m mujoco.viewer --mjcf=terrain/first_terrain_preview.xml
```

---

## Contents

Documentation here is the developer reference. The narrative version, with figures,
is on the [MyoAssist site](https://neumovelab.github.io/myoassist/modeling/terrains/).

- [Concepts](docs/concepts.md): grid, tiles, connectors, the boundary contract, palette, texture, randomization, surface queries.
- [Tile catalog](docs/tiles.md): all nine tile types with parameter tables, generated from the registry.
- [Configuration schema](docs/configuration.md): both config forms in full.
- [CLI reference](docs/cli.md): the `myoassist-terrains` commands.
- [Python API](docs/python-api.md): the stable public surface.
- [Velocity maps](docs/velocity-maps.md): sampling and rendering 3D target-velocity fields over a terrain.
- [Project layout for users](docs/project-layout.md): expected project structure and include chaining.
- [Utilities and example configs](docs/utilities.md): bundled configs, style templates, render tooling.
- [Extending](docs/extending.md): adding a custom tile type.
- [Development](docs/development.md): running the suite, and what it covers.

Changes, including the ones that alter emitted geometry, are recorded in
[CHANGELOG.md](CHANGELOG.md).

---

## License

Apache 2.0. See [LICENSE](LICENSE).
