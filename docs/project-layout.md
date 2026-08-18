# Project layout for users

Project structure (e.g. a MyoAssist model repo) is expected to look like:

```
my_user_project/
├── terrain_config.xml        # active-terrain pointer; chains style + terrain
├── terrain_style.xml         # user-editable visuals (skybox, fog, lights)
├── terrain/                  # output of `myoassist-terrains build`
│   ├── flat_smoke_test.xml
│   ├── my_scene.xml
│   ├── my_scene_rough_r1c0_7b55edf2.png   # hfield assets for rough tiles
│   └── ...
└── models/
    └── my_model.xml          # user model; includes terrain_config.xml
```

The user model includes the active-terrain pointer like:

```xml
<mujoco model="my_model">
  <!-- ... your model body, joints, etc ... -->
  <include file="../terrain_config.xml"/>
</mujoco>
```

`terrain_config.xml` in turn chains two includes:

```xml
<mujocoinclude>
  <include file="../terrain_style.xml"/>
  <include file="../terrain/my_scene.xml"/>
</mujocoinclude>
```

**Path resolution note.** MuJoCo resolves nested `<include>` paths relative to
the **top-level model file's directory**, not relative to the file containing
the `<include>`. The `../` prefix climbs out of the model directory before
descending into `terrain/`. The bundled templates assume the user model
lives one level below the project root.

Heightmap file names carry a short digest of their contents. MuJoCo caches decoded
file assets by path within a process, so a name derived only from the terrain and
tile would serve a stale heightfield to any rebuild under the same name. A
consequence: re-tuning a `rough` tile writes a new file, and `myoassist-terrains
build` removes the superseded one.

See `utils/style/` for a working `terrain_config.xml` / `terrain_style.xml` pair,
including the `CONCRETE.png` texture used by the default base config.
