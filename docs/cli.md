# CLI reference

The package installs as `myoassist-terrains`. Equivalent to
`python -m myoassist_terrains`.

```bash
# Build a terrain XML from a JSON config (and optionally activate it).
myoassist-terrains build path/to/config.json [--activate]

# Switch the active terrain pointer (rewrites the include in terrain_config.xml).
myoassist-terrains set-active <terrain_name>

# List all terrains in the current project's terrain library, marking the active one.
myoassist-terrains list

# Emit a <mujoco>-rooted wrapper that loads ONLY the terrain (no user model).
# Useful for visual QC.
myoassist-terrains preview <terrain_name>
```

The CLI discovers the project root by walking up from CWD looking for
`terrain_config.xml`. To override, set `MYOASSIST_TERRAINS_ROOT=/path/to/project`.
