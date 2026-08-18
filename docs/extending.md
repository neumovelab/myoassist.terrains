# Extending: adding a custom tile type

A tile module supplies six things. The first four existed in v1; `surface_height`
and `SPEED_SCALE` are what let the rest of the package describe your tile rather
than guess at it.

1. `DEFAULT_RGBA`, `DEFAULT_PARAMS`, `PARAM_RANGES`, `PARAM_DOCS`
2. `SPEED_SCALE`: the velocity map's speed multiplier for this tile (1.0 is flat)
3. `emit(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params)
   -> TileEmitResult`
4. `surface_height(local_x, local_y, *, tile_size, **params) -> float`

Then add the module to `_MODULES` in `src/myoassist_terrains/tiles/__init__.py`.
Registration is explicit, not an import-time side effect, so the active tile set is
visible in one place.

**`emit` and `surface_height` must agree.** They are two views of the same
geometry: `emit` places it, `surface_height` answers how high the walkable surface
is at a point. Share the span arithmetic between them through a helper in the same
module rather than deriving it twice. `tests/test_surface_contract.py` ray-casts the
compiled model and fails if they disagree, and it will pick up your tile
automatically once it is in the registry.

**Honor the boundary contract.** Present a flat top at `base_height` around the
whole perimeter, so connectors join cleanly. `gap` is the only tile exempt from
this, because a trench reaching the tile edge is its whole purpose.

## Plugin-style registration, without forking

```python
from myoassist_terrains import register_tile
from myoassist_terrains.tiles.base import TileEmitResult


def emit_my_tile(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params):
    # ... add geoms to spec.worldbody ...
    return TileEmitResult(base_height=params.get("base_height", 0.0))


def my_tile_height(local_x, local_y, *, tile_size, base_height=0.0, **_):
    return float(base_height)


register_tile(
    "my_tile",
    emit_my_tile,
    default_params={"base_height": 0.0},
    param_ranges={},
    default_rgba=(0.7, 0.7, 0.7, 1.0),
    surface_height=my_tile_height,
    speed_scale=0.8,
    param_docs={"base_height": "z-coordinate of the tile's flat-edge base."},
)
```

`"my_tile"` is then a valid `"type"` in any config, and the velocity map and
`surface_height_at` describe it correctly. Omitting `surface_height` falls back to
reporting the tile's `base_height`, which is only right for a flat-topped tile;
omitting `speed_scale` gives it flat-terrain speed.
