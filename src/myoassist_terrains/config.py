"""Configuration schema for terrain build inputs (JSON-driven).

A `TerrainConfig` describes a complete terrain to generate: grid layout,
border (connector) rules, palette, optional uniform-mode texture, and
either an explicit list of tile placements (`tiles`), a randomization spec
(`randomization`), or both (explicit cells fixed; remaining cells sampled).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
        if self.palette_preset not in {"diverse", "uniform", "custom"}:
            raise ValueError(f"palette_preset must be one of {{'diverse','uniform','custom'}}, got {self.palette_preset!r}")
        if not self.terrain_name:
            raise ValueError("terrain_name is required and must be non-empty")
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
# Loader


def load_config(path: Path) -> TerrainConfig:
    """Load and validate a terrain config from JSON."""
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return _config_from_dict(raw)


def _config_from_dict(raw: dict[str, Any]) -> TerrainConfig:
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

    texture_raw = raw.get("texture")
    texture: TextureConfig | None = None
    if texture_raw is not None:
        if isinstance(texture_raw, str):
            # Convenience: bare-string form sets just the file path.
            texture = TextureConfig(file=texture_raw)
        else:
            texture = TextureConfig(
                file=str(texture_raw["file"]),
                name=str(texture_raw.get("name", "terrain_texture")),
                repeat=tuple(texture_raw.get("repeat", (4.0, 4.0))),  # type: ignore[arg-type]
                texuniform=bool(texture_raw.get("texuniform", True)),
            )

    return TerrainConfig(
        terrain_name=str(raw["terrain_name"]),
        grid=grid,
        border=border,
        palette_preset=str(raw.get("palette_preset", "diverse")),
        palette={k: list(v) for k, v in raw.get("palette", {}).items()},
        tiles=tiles,
        randomization=randomization,
        texture=texture,
    )
