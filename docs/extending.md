# Extending: adding a custom tile type

1. Drop a new module `src/myoassist_terrains/tiles/my_tile.py` with `DEFAULT_RGBA`,
   `DEFAULT_PARAMS`, `PARAM_RANGES`, and an `emit(spec, origin_xyz, name, *,
   tile_size, rgba=None, material=None, **params) -> TileEmitResult` function.
2. Wire it into `src/myoassist_terrains/tiles/__init__.py` so it appears in
   `REGISTRY` automatically.

Or, for plugin-style registration without forking:

```python
from myoassist_terrains import register_tile
from myoassist_terrains.tiles.base import TileEmitResult

def emit_my_tile(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params):
    # ... add geoms to spec.worldbody ...
    return TileEmitResult(base_height=0.0)

register_tile(
    "my_tile",
    emit_my_tile,
    default_params={"height": 0.0},
    param_ranges={"height": (0.0, 1.0)},
    default_rgba=(0.7, 0.7, 0.7, 1.0),
)
```

After registration, `"my_tile"` is a valid `"type"` value in any config.
