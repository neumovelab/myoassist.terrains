"""Configuration schema for terrain build inputs (JSON-driven).

Two config forms are recognized by the loader:

1. Grid/tile form -> a `TerrainConfig`: a complete terrain built by tiling
   finite box/hfield cells across a grid, with border (connector) rules,
   palette, optional texture, and either an explicit list of tile placements
   (`tiles`), a randomization spec (`randomization`), or both.

2. Uniform form -> a `UniformTerrainConfig`: a single continuous walkable
   surface, selected by a top-level `"terrain"` string
   (`flat` | `slope` | `random` | `sinusoidal`). `flat`/`slope` emit one
   plane; `random`/`sinusoidal` emit one heightfield with a smooth safe zone
   near the origin. See `uniform.py` and `composer._build_uniform`.

`load_config` / `_config_from_dict` dispatch on which form the JSON matches;
`build_terrain` accepts either kind of config object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PALETTE_PRESETS = frozenset({"diverse", "uniform", "custom"})


def _validate_terrain_name(name: str) -> None:
    r"""`terrain_name` becomes a filename, so it has to be a bare one.

    Without this a name containing a separator or `..` writes the generated XML
    outside the terrain library, where `set-active` cannot find it again.

    Both separators are rejected on every platform, deliberately. `Path` only treats
    `\` as one on Windows, so relying on it would make `{"terrain_name": "a\b"}`
    an error on Windows and a legal filename on Linux -- and a config is a shared
    artifact that gets built on both.
    """
    if not name:
        raise ValueError("terrain_name is required and must be non-empty")
    if "/" in name or "\\" in name or name in {".", ".."} or name != Path(name).name:
        raise ValueError(
            f"terrain_name must be a bare file name (no path separators or '..'), got {name!r}; "
            f"it is used as the generated file name terrain/<terrain_name>.xml."
        )


def _reject_unknown_keys(raw: dict[str, Any], known: set[str], form: str) -> None:
    """Reject unrecognised top-level keys.

    Silently ignoring them means a typo changes the terrain without saying so: a
    config asking for `{"terrain": "slope", "dge": 8}` used to build flat ground
    and pass validation, which is a wrong-experiment failure rather than a crash.
    Keys starting with `_` are allowed through as comments, matching the
    `_comment` convention used in the bundled render configs.
    """
    unknown = sorted(k for k in raw if k not in known and not k.startswith("_"))
    if unknown:
        raise ValueError(
            f"Unknown key(s) {unknown} in the {form} terrain config. Valid keys: {sorted(known)}. "
            f"Prefix a key with '_' to keep it as a comment."
        )


# ---------------------------------------------------------------------------
# Dataclass definitions


@dataclass
class GridConfig:
    rows: int
    cols: int
    tile_size: tuple[float, float]  # (width_x, length_y) in meters

    def __post_init__(self) -> None:
        self.tile_size = tuple(self.tile_size)  # type: ignore[assignment]
        if self.rows < 1 or self.cols < 1:
            raise ValueError(f"Grid must have rows >= 1 and cols >= 1, got {self}")
        if len(self.tile_size) != 2 or any(s <= 0 for s in self.tile_size):
            raise ValueError(f"tile_size must be 2 positive floats, got {self.tile_size}")


@dataclass
class BorderConfig:
    width: float = 0.5  # meters of flat connector strip between tiles
    match_mode: str = "min"  # how to choose connector base height: 'min' | 'max' | 'mean'

    def __post_init__(self) -> None:
        if self.width < 0:
            raise ValueError(f"border.width must be >= 0, got {self.width}")
        if self.match_mode not in {"min", "max", "mean"}:
            raise ValueError(f"border.match_mode must be one of {{'min','max','mean'}}, got {self.match_mode!r}")


@dataclass
class TileConfig:
    row: int
    col: int
    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RandomizationSpec:
    """Per-cell randomization. Cells not covered by an explicit `tiles` entry
    are filled by sampling a tile type from `weights`, then sampling each of
    its parameters from either the user-supplied range in `param_ranges` or
    the tile's built-in `PARAM_RANGES` (degenerate range [v, v] fixes a
    parameter at v). Categorical parameters (axis, direction, ...) aren't
    randomized -- they fall through to tile defaults unless a fixed override
    is supplied via `param_ranges`.
    """

    seed: int = 0
    weights: dict[str, float] = field(default_factory=dict)
    # Per-tile-type param specs. Each spec is either [lo, hi] for a numeric
    # range or a list of categorical choices (strings/bools).
    param_ranges: dict[str, dict[str, list]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("randomization.weights cannot be empty")
        for type_name, w in self.weights.items():
            if w < 0:
                raise ValueError(f"randomization.weights[{type_name!r}] must be >= 0 (got {w})")
        if sum(self.weights.values()) <= 0:
            raise ValueError("randomization.weights must include at least one positive entry")


@dataclass
class TextureConfig:
    """Optional 2D texture applied to the uniform palette material.

    `file` is resolved relative to the JSON config's parent directory at
    build time, then rewritten to a path that resolves relative to the
    consuming model's directory in the emitted XML. `repeat` controls how
    many times the texture tiles per geom; larger values mean smaller
    visible repeats. `texuniform` makes the repeat count constant per geom
    rather than scaled by geom size -- usually what you want for terrain
    where neighbouring tiles should look uniform.
    """

    file: str
    name: str = "terrain_texture"
    repeat: tuple[float, float] = (4.0, 4.0)
    texuniform: bool = True

    def __post_init__(self) -> None:
        if not self.file:
            raise ValueError("texture.file must be a non-empty path")
        self.repeat = tuple(self.repeat)  # type: ignore[assignment]
        if len(self.repeat) != 2:
            raise ValueError(f"texture.repeat must have 2 entries, got {self.repeat}")


@dataclass
class TerrainConfig:
    terrain_name: str
    grid: GridConfig
    border: BorderConfig
    palette_preset: str = "diverse"  # 'diverse' | 'uniform' | 'custom'
    palette: dict[str, list[float]] = field(default_factory=dict)  # type_name -> rgba
    tiles: list[TileConfig] = field(default_factory=list)
    randomization: RandomizationSpec | None = None
    texture: TextureConfig | None = None

    def __post_init__(self) -> None:
        if self.palette_preset not in PALETTE_PRESETS:
            raise ValueError(f"palette_preset must be one of {sorted(PALETTE_PRESETS)}, got {self.palette_preset!r}")
        _validate_terrain_name(self.terrain_name)
        # A cell can hold one tile. Two entries for the same cell used to emit
        # overlapping geometry, or collide on a geom name inside MuJoCo, depending
        # on whether the types matched.
        seen: set[tuple[int, int]] = set()
        for t in self.tiles:
            if (t.row, t.col) in seen:
                raise ValueError(f"Duplicate tile at (row={t.row}, col={t.col}); each cell may hold only one tile.")
            seen.add((t.row, t.col))
        if not self.tiles and self.randomization is None:
            raise ValueError(
                "Config must include either 'tiles' (explicit per-cell placement), "
                "'randomization' (per-cell sampling), or both (explicit cells fixed; "
                "remaining cells filled by sampling)."
            )
        # Validate tile coordinates fit within the grid.
        for t in self.tiles:
            if not (0 <= t.row < self.grid.rows and 0 <= t.col < self.grid.cols):
                raise ValueError(
                    f"Tile {t.type} at (row={t.row}, col={t.col}) is outside the grid ({self.grid.rows}x{self.grid.cols})"
                )


# ---------------------------------------------------------------------------
# Uniform (single-surface) config


UNIFORM_TERRAIN_TYPES = frozenset({"flat", "slope", "random", "sinusoidal"})


@dataclass
class UniformTerrainConfig:
    """A single uniform terrain surface (one plane or one heightfield).

    Selected by a top-level `"terrain"` string rather than a `grid` + `tiles`
    layout. `flat`/`slope` map to a `mjGEOM_PLANE`; `random`/`sinusoidal` map
    to a single heightfield covering `extent` x `extent` meters with a smooth
    safe zone of `safe_zone_radius` around the origin.

    Styling reuses the tile path's uniform-material machinery: by default the
    surface gets the shared `myoassist_mat_uniform` material (rgba tracks
    `terrain_style.xml`). Override the color per config via `palette` (an rgba
    under the key `"terrain"`, `"uniform"`, or the terrain type name) and/or
    apply a `texture`.
    """

    terrain: str  # 'flat' | 'slope' | 'random' | 'sinusoidal'
    terrain_name: str = ""
    deg: float = 0.0  # slope grade in degrees (terrain='slope')
    amplitude: float = 0.1  # heightfield relief in meters (random/sinusoidal)
    period: float = 1.0  # sinusoid wavelength along +x in meters (sinusoidal)
    seed: int = 0  # RNG seed (terrain='random')
    extent: float = 20.0  # full side length of the surface in meters
    resolution: int = 256  # heightfield grid resolution (nrow == ncol)
    safe_zone_radius: float = 3.0  # flattened reset radius around origin (m)
    base_depth: float = 1.0  # solid heightfield thickness below the surface (m)
    # Styling (mirrors TerrainConfig; uniform terrains are single-surface so
    # 'uniform' is the natural default preset).
    palette_preset: str = "uniform"
    palette: dict[str, list[float]] = field(default_factory=dict)
    texture: TextureConfig | None = None

    def __post_init__(self) -> None:
        if self.terrain not in UNIFORM_TERRAIN_TYPES:
            raise ValueError(f"terrain must be one of {sorted(UNIFORM_TERRAIN_TYPES)}, got {self.terrain!r}")
        if not self.terrain_name:
            self.terrain_name = f"uniform_{self.terrain}"
        _validate_terrain_name(self.terrain_name)
        if self.palette_preset not in PALETTE_PRESETS:
            raise ValueError(f"palette_preset must be one of {sorted(PALETTE_PRESETS)}, got {self.palette_preset!r}")
        if self.extent <= 0:
            raise ValueError(f"extent must be > 0, got {self.extent}")
        if self.resolution < 8:
            raise ValueError(f"resolution must be >= 8, got {self.resolution}")
        if self.safe_zone_radius < 0:
            raise ValueError(f"safe_zone_radius must be >= 0, got {self.safe_zone_radius}")
        if self.base_depth <= 0:
            raise ValueError(f"base_depth must be > 0, got {self.base_depth}")
        if self.terrain in {"random", "sinusoidal"} and self.amplitude <= 0:
            raise ValueError(f"{self.terrain} terrain requires amplitude > 0, got {self.amplitude}")
        if self.terrain == "sinusoidal" and self.period <= 0:
            raise ValueError(f"sinusoidal terrain requires period > 0, got {self.period}")
        if self.terrain == "slope" and not (-90.0 < self.deg < 90.0):
            raise ValueError(f"slope deg must satisfy -90 < deg < 90, got {self.deg}")


# ---------------------------------------------------------------------------
# Loader


def load_config(path: Path) -> TerrainConfig | UniformTerrainConfig:
    """Load and validate a terrain config from JSON (grid or uniform form)."""
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return _config_from_dict(raw)


def config_from_dict(
    raw: dict[str, Any],
) -> TerrainConfig | UniformTerrainConfig:
    """Build a validated config (grid or uniform form) from an in-memory dict.

    Public companion to :func:`load_config` (which reads from a path). Consumers that
    already hold a config dict (e.g. an in-memory compose pipeline) should use this
    rather than reaching for the private ``_config_from_dict``.
    """
    return _config_from_dict(raw)


def _config_from_dict(
    raw: dict[str, Any],
) -> TerrainConfig | UniformTerrainConfig:
    # Uniform (single-surface) form is selected by a top-level `terrain`
    # string. The grid/tile form never carries this key, so the dispatch is
    # unambiguous and the two forms coexist.
    if isinstance(raw.get("terrain"), str):
        return _uniform_from_dict(raw)
    return _grid_config_from_dict(raw)


_UNIFORM_KEYS = {
    "terrain",
    "terrain_name",
    "deg",
    "amplitude",
    "period",
    "seed",
    "extent",
    "resolution",
    "safe_zone_radius",
    "base_depth",
    "palette_preset",
    "palette",
    "texture",
}
_GRID_KEYS = {
    "terrain_name",
    "grid",
    "border",
    "palette_preset",
    "palette",
    "tiles",
    "randomization",
    "texture",
}


def _uniform_from_dict(raw: dict[str, Any]) -> UniformTerrainConfig:
    _reject_unknown_keys(raw, _UNIFORM_KEYS, "uniform")
    texture = _texture_from_raw(raw.get("texture"))
    return UniformTerrainConfig(
        terrain=str(raw["terrain"]),
        terrain_name=str(raw.get("terrain_name", "")),
        deg=float(raw.get("deg", 0.0)),
        amplitude=float(raw.get("amplitude", 0.1)),
        period=float(raw.get("period", 1.0)),
        seed=int(raw.get("seed", 0)),
        extent=float(raw.get("extent", 20.0)),
        resolution=int(raw.get("resolution", 256)),
        safe_zone_radius=float(raw.get("safe_zone_radius", 3.0)),
        base_depth=float(raw.get("base_depth", 1.0)),
        palette_preset=str(raw.get("palette_preset", "uniform")),
        palette={k: list(v) for k, v in raw.get("palette", {}).items()},
        texture=texture,
    )


def _texture_from_raw(texture_raw: Any) -> TextureConfig | None:
    """Parse the shared `texture` config field (bare-string or object form)."""
    if texture_raw is None:
        return None
    if isinstance(texture_raw, str):
        # Convenience: bare-string form sets just the file path.
        return TextureConfig(file=texture_raw)
    return TextureConfig(
        file=str(texture_raw["file"]),
        name=str(texture_raw.get("name", "terrain_texture")),
        repeat=tuple(texture_raw.get("repeat", (4.0, 4.0))),  # type: ignore[arg-type]
        texuniform=bool(texture_raw.get("texuniform", True)),
    )


def _grid_config_from_dict(raw: dict[str, Any]) -> TerrainConfig:
    _reject_unknown_keys(raw, _GRID_KEYS, "grid")
    grid_raw = raw.get("grid", {})
    grid = GridConfig(
        rows=int(grid_raw["rows"]),
        cols=int(grid_raw["cols"]),
        tile_size=tuple(grid_raw["tile_size"]),  # type: ignore[arg-type]
    )

    border_raw = raw.get("border", {})
    border = BorderConfig(
        width=float(border_raw.get("width", 0.5)),
        match_mode=str(border_raw.get("match_mode", "min")),
    )

    tiles = [
        TileConfig(
            row=int(t["row"]),
            col=int(t["col"]),
            type=str(t["type"]),
            params=dict(t.get("params", {})),
        )
        for t in raw.get("tiles", [])
    ]

    rand_raw = raw.get("randomization")
    randomization: RandomizationSpec | None = None
    if rand_raw is not None:
        # Each param's value can be either a numeric range [lo, hi] or a list
        # of categorical choices (strings or bools). Accept whatever the user
        # supplies as-is and let the composer dispatch.
        param_ranges_raw: dict[str, dict[str, list]] = {}
        for type_name, ranges in rand_raw.get("param_ranges", {}).items():
            type_ranges: dict[str, list] = {}
            for p, spec in ranges.items():
                type_ranges[str(p)] = list(spec)
            param_ranges_raw[str(type_name)] = type_ranges

        randomization = RandomizationSpec(
            seed=int(rand_raw.get("seed", 0)),
            weights={str(k): float(v) for k, v in rand_raw.get("weights", {}).items()},
            param_ranges=param_ranges_raw,
        )

    return TerrainConfig(
        terrain_name=str(raw["terrain_name"]),
        grid=grid,
        border=border,
        palette_preset=str(raw.get("palette_preset", "diverse")),
        palette={k: list(v) for k, v in raw.get("palette", {}).items()},
        tiles=tiles,
        randomization=randomization,
        # One texture parser for both config forms; the grid path used to carry a
        # verbatim copy of it.
        texture=_texture_from_raw(raw.get("texture")),
    )
