"""Where is the ground? Public surface-height queries over a terrain config.

A consumer that has to place something on the terrain -- seat a model at reset,
drop a marker, lift a velocity-map sample -- needs the walkable surface height at
a world coordinate. Deriving it from the compiled model means collision-probing,
which is fragile: myoassist's seating probe used a 50 m contact margin, and at
that margin MuJoCo's mesh-versus-large-box narrowphase stops returning physical
distances, so composed models ended up buried 1.6-2.6 m or flung 24 m up.

The terrain package knows the answer exactly, so it answers directly. Both
queries take a config, not a compiled model, and dispatch to the same per-tile
`surface_height` functions the tiles use to place their geometry.

    surface_height_at(config, x, y)                  -- point query
    max_surface_height_in(config, x, y, radius)      -- footprint query

Use the footprint query for anything with extent, such as a foot: a point query
between two stepping stones reports the base slab and would seat a foot inside a
stone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from myoassist_terrains import uniform as uniform_gen
from myoassist_terrains.config import TerrainConfig, TileConfig, UniformTerrainConfig
from myoassist_terrains.tiles import REGISTRY


__all__ = ["surface_height_at", "max_surface_height_in", "TerrainSurface"]


def cell_base_height(tile: TileConfig) -> float:
    """The height a tile presents around its perimeter.

    This is what the composer negotiates connector heights against, and it is
    derivable from the config alone -- `emit` reports the same value back through
    `TileEmitResult.base_height`.
    """
    params = dict(REGISTRY[tile.type].default_params)
    params.update(tile.params)
    if "base_height" in params:
        return float(params["base_height"])
    return float(params.get("height", 0.0))


def _match(mode: str, heights: list[float]) -> float:
    if mode == "min":
        return min(heights)
    if mode == "max":
        return max(heights)
    if mode == "mean":
        return sum(heights) / len(heights)
    raise ValueError(f"Unknown match_mode {mode!r}")


def _axis_slot(value: float, first_center: float, extent: float, pitch: float, count: int):
    """Locate `value` along one grid axis.

    Returns `("in", i)` inside cell i, `("between", i)` in the strip between i
    and i+1, or `("outside", None)` beyond the grid.
    """
    half = extent / 2.0
    for i in range(count):
        center = first_center + i * pitch
        if value < center - half:
            # Before cell i: either the strip after i-1, or off the grid.
            return ("between", i - 1) if i > 0 else ("outside", None)
        if value <= center + half:
            return ("in", i)
    return ("outside", None)


@dataclass
class TerrainSurface:
    """A reusable surface query over one terrain config.

    Resolving the tiles and computing the cell layout are done once here rather
    than per call. That matters: the velocity map asks five height questions per
    sample, and rebuilding a 225-entry layout map each time accounted for roughly
    60% of a 15x15 render's runtime.
    """

    config: TerrainConfig | UniformTerrainConfig

    def __post_init__(self) -> None:
        self._uniform = isinstance(self.config, UniformTerrainConfig)
        if self._uniform:
            return
        # Imported here to avoid a cycle: composer imports the tiles, tiles do
        # not import this module, and this module needs the composer's layout.
        from myoassist_terrains.composer import compute_cell_layouts, resolve_tiles

        cfg = self.config
        self._layouts = compute_cell_layouts(cfg)
        self._tiles = {(t.row, t.col): t for t in resolve_tiles(cfg)}
        self._base = {rc: cell_base_height(t) for rc, t in self._tiles.items()}
        # Merge each tile's params once. Doing it per query cost more than the
        # height evaluation itself: seating a model asks hundreds of questions.
        self._call: dict[tuple[int, int], tuple] = {}
        for rc, tile in self._tiles.items():
            impl = REGISTRY[tile.type]
            params = dict(impl.default_params)
            params.update(tile.params)
            self._call[rc] = (impl.surface_height_fn, params)
        self._tw, self._tl = cfg.grid.tile_size
        pitch = cfg.border.width
        self._pitch_x = self._tw + pitch
        self._pitch_y = self._tl + pitch
        self._x_first = -(cfg.grid.cols * self._tw + (cfg.grid.cols - 1) * pitch) / 2 + self._tw / 2
        self._y_first = -(cfg.grid.rows * self._tl + (cfg.grid.rows - 1) * pitch) / 2 + self._tl / 2

    def height_at(self, x: float, y: float) -> float:
        """Walkable surface height at world (x, y), or 0.0 beyond the terrain."""
        cfg = self.config
        if self._uniform:
            return uniform_gen.surface_height(cfg, x, y)

        kind_x, ix = _axis_slot(x, self._x_first, self._tw, self._pitch_x, cfg.grid.cols)
        kind_y, iy = _axis_slot(y, self._y_first, self._tl, self._pitch_y, cfg.grid.rows)
        if kind_x == "outside" or kind_y == "outside":
            return 0.0

        if kind_x == "in" and kind_y == "in":
            call = self._call.get((iy, ix))
            if call is None:
                return 0.0
            height_fn, params = call
            if height_fn is None:
                return self._base[(iy, ix)]
            layout = self._layouts[(iy, ix)]
            return float(height_fn(x - layout.center_x, y - layout.center_y, tile_size=(self._tw, self._tl), **params))

        # In a connector strip: its top face is match_mode over the cells it
        # joins, exactly as the composer emits it. Reporting 0.0 here (as the
        # previous implementation did) is wrong whenever a tile sits off zero.
        if kind_x == "between" and kind_y == "in":
            cells = [(iy, ix), (iy, ix + 1)]
        elif kind_x == "in" and kind_y == "between":
            cells = [(iy, ix), (iy + 1, ix)]
        else:
            cells = [(iy, ix), (iy, ix + 1), (iy + 1, ix), (iy + 1, ix + 1)]

        heights = [self._base[rc] for rc in cells if rc in self._base]
        if not heights:
            return 0.0
        return _match(cfg.border.match_mode, heights)

    def max_height_in(self, x: float, y: float, radius: float, samples: int = 5) -> float:
        """Highest surface height within `radius` of (x, y).

        Sampled on a grid clipped to the disc, plus the centre. A foot has extent,
        so a point query can miss the stone or obstacle it is actually resting on;
        this is the query to use when placing something that occupies area.
        """
        if radius <= 0.0:
            return self.height_at(x, y)
        best = self.height_at(x, y)
        offsets = np.linspace(-radius, radius, max(2, int(samples)))
        for dx in offsets:
            for dy in offsets:
                if dx * dx + dy * dy > radius * radius:
                    continue
                best = max(best, self.height_at(x + float(dx), y + float(dy)))
        return best


def surface_height_at(config: TerrainConfig | UniformTerrainConfig, x: float, y: float) -> float:
    """Walkable surface height at world (x, y) for either config form.

    Beyond the terrain footprint this returns 0.0. Build a `TerrainSurface` once
    instead if you are making many queries against the same config.
    """
    return TerrainSurface(config).height_at(x, y)


def max_surface_height_in(
    config: TerrainConfig | UniformTerrainConfig,
    x: float,
    y: float,
    radius: float,
    samples: int = 5,
) -> float:
    """Highest surface height within `radius` of (x, y). See `TerrainSurface`."""
    return TerrainSurface(config).max_height_in(x, y, radius, samples=samples)
