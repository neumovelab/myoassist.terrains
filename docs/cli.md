# CLI reference

The package installs the `myoassist-terrains` console script. `python -m
myoassist_terrains` is equivalent, including the exit code.

```bash
# Build a terrain XML from a JSON config (and optionally activate it).
myoassist-terrains build path/to/config.json [--activate]

# Switch the active terrain pointer (rewrites the include in terrain_config.xml).
myoassist-terrains set-active <terrain_name>

# List all terrains in the project's terrain library, marking the active one.
myoassist-terrains list

# Emit a <mujoco>-rooted wrapper that loads ONLY the terrain (no user model).
myoassist-terrains preview <terrain_name>

myoassist-terrains --version
```

Every subcommand takes `--root <dir>` to name the project explicitly. Without it
the project root is discovered by walking up from the working directory looking for
`terrain_config.xml`, or taken from `MYOASSIST_TERRAINS_ROOT` (the older
`MYO_TERRAIN_ROOT` is still honored).

`<terrain_name>` is the name inside the config, which is not necessarily the config
file's name. `list` shows what a library actually holds.

## Notes

`build` writes `terrain/<terrain_name>.xml` plus any heightmap assets, and removes
superseded heightmaps for that terrain. Asset names carry a content digest, so
re-tuning a `rough` tile produces a new file rather than overwriting one that a
loaded model may still reference.

`preview` chains the project's `terrain_style.xml` when there is one, so the scene
is lit and skyboxed. A generated terrain file carries only `<asset>` and
`<worldbody>`, so without that include a preview renders unlit geometry on a black
background. It also declares a 1920x1080 offscreen framebuffer, since MuJoCo
defaults to 640x480.
