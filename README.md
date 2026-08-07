# myoassist.terrains

**Modular procedural terrain generator for MuJoCo, designed to be used by [MyoAssist](https://github.com/neumovelab/myoassist) and other musculoskeletal-simulation projects within [MyoSuite](https://myosuite.readthedocs.io/en/latest/).**

`myoassist_terrains` turns a small JSON description of a grid layout into a
ready-to-include MuJoCo MJCF fragment containing tiles, connectors, materials
and (optionally) heightfield assets. It supports explicit per-cell placement,
weighted-random sampling per cell, parametric variation of every tile type,
and a single shared texture for uniform-palette terrains.

```
┌──────────────────────────────────────────────────────────────────┐
│  JSON config  ──►  build_terrain()  ──►  MjSpec  ──►  XML include│
│                       (Python API)          (compose)    (CLI)   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Getting started

### Installation

The package is published as a normal Python package and is utilized via
`pip install -e .` (editable) or `pip install .` for a frozen build.

```bash
git clone https://github.com/neumovelab/myoassist.terrains.git
cd myoassist.terrains
pip install -e .

# Optional extras
pip install -e ".[render]"   # adds mediapy for ensemble renders
pip install -e ".[dev]"      # adds pytest for unit tests
```

Requires Python `>=3.10` and `mujoco>=3.3.3`.

### Quick start

Author a config:

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

The CLI writes `terrain/first_terrain.xml` into the project directory and (with
`--activate`) updates the `<include file="terrain/first_terrain.xml"/>` line in
`terrain_config.xml`. Any user model that includes `terrain_config.xml`
now sees the new terrain.

Preview it without a user model:

```bash
myoassist-terrains preview first_terrain
python -m mujoco.viewer --mjcf=terrain/first_terrain_preview.xml
```

---

## Contents

Detailed documentation lives under [`docs/`](docs/):

- [Concepts](docs/concepts.md) — grid, tiles, connectors, boundary contract, palette, texture, randomisation.
- [Tile catalog](docs/tiles.md) — all nine tile types with parameter tables.
- [Configuration schema](docs/configuration.md) — the full JSON config reference.
- [CLI reference](docs/cli.md) — the `myoassist-terrains` commands.
- [Python API](docs/python-api.md) — the stable public surface + examples.
- [Velocity maps](docs/velocity-maps.md) — sampling and rendering 3D target-velocity fields over a terrain.
- [Project layout for users](docs/project-layout.md) — expected project structure and include chaining.
- [Utilities and example configs](docs/utilities.md) — bundled configs, style templates, and render tooling.
- [Extending: adding a custom tile type](docs/extending.md) — registering new tile types.
- [Development](docs/development.md) — running the test suite.

---

## License

Apache 2.0. See [LICENSE](LICENSE).
