"""Composer: takes a TerrainConfig, builds an MjSpec by placing tiles on a
grid, fills border connectors and corner pieces between them, and returns
the populated spec.

Coordinate convention
---------------------
- Grid is centered at the world origin (0, 0).
- Cell (row=0, col=0) is at the most negative (x, y); rows increase in +y,
  cols increase in +x.
- Each tile's `origin_xyz` is its center on the grid plane (z=0).
- Per-tile `height` parameters offset the tile's top surface above z=0.

Border / connectors
-------------------
- Cells are spaced by `tile_size + border.width` so borders are additive,
  not eaten out of tile area.
- For each interior edge between two cells, we emit a flat box geom of width
  `border.width`, length = perpendicular tile_size. Top face = `match_mode`
  applied to the two adjacent base heights.
- For each interior 4-way corner, we emit a small `border.width` x
  `border.width` box. Top face = `match_mode` applied to all 4 surrounding
  base heights.

Boundary contract: tiles always present a flat top at their declared base
height around their full perimeter (v1 flat-at-base contract).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mujoco as mj
import numpy as np

from myoassist_terrains import uniform as uniform_gen
from myoassist_terrains.config import (
    TerrainConfig,
    TextureConfig,
    TileConfig,
    UniformTerrainConfig,
)
from myoassist_terrains.registry import lookup
from myoassist_terrains.tiles import REGISTRY
from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Material name for uniform-mode geoms. Distinct from `terrain_mat` (the
# user-tunable material in terrain_style.xml that legacy content uses) so
# the generated spec can self-declare its own copy without needing to know
# anything that lives in the chained include file.
_UNIFORM_MATERIAL_NAME = "myoassist_mat_uniform"
# Mirror the rgba of the style file's `terrain_mat` so uniform mode looks
# the same as the legacy convention. If you retune terrain_mat's rgba in
# terrain_style.xml, update this constant to match.
_UNIFORM_RGBA: tuple[float, float, float, float] = (0.78, 0.78, 0.78, 1.0)
_UNIFORM_SPECULAR = 0.5
_UNIFORM_SHININESS = 0.5
# Default floor styling for uniform terrain -- mirrors the legacy `matfloor`:
# a built-in flat 2D texture (a muted blue-grey) with edge marks (a fine grid)
# and low reflectance.  Overridable via config.texture / config.palette.
_MATFLOOR_RGB1: tuple[float, float, float] = (0.353, 0.439, 0.529)
_MATFLOOR_MARKRGB: tuple[float, float, float] = (0.8, 0.8, 0.8)
_MATFLOOR_REFLECTANCE = 0.05
# Rendered grid spacing (m) for uniform planes; matches the legacy plane's
# `size="0 0 0.05"`.  half_x = half_y = 0 renders an infinite plane; a plane is
# analytically infinite for collision regardless.
_PLANE_GRID_SPACING = 0.05

# Material name prefix for diverse/custom-mode palette materials registered
# in the generated terrain XML's <asset> block.
_PALETTE_MATERIAL_PREFIX = "myoassist_mat_"

# Connector default rgba in diverse/custom mode (a neutral gray that recedes
# visually between brightly-colored tiles).
_CONNECTOR_DEFAULT_RGBA = (0.65, 0.65, 0.65, 1.0)
# Specular / shininess for connector materials (matches built-tile defaults).
_CONNECTOR_SPECULAR = 0.5
_CONNECTOR_SHININESS = 0.5


@dataclass
class _CellLayout:
    row: int
    col: int
    center_x: float
    center_y: float


@dataclass
class _Appearance:
    """How a single tile/connector geom should be colored."""

    rgba: tuple[float, float, float, float] | None = None
    material: str | None = None


# ---------------------------------------------------------------------------
# Public entry point


def _read_uniform_rgba_from_style(
    output_dir: Optional[Path],
) -> tuple[float, float, float, float]:
    """Read terrain_style.xml's `terrain_mat` rgba so uniform mode tracks
    the user's manual edits to the style file.

    The style file lives one level above `output_dir` (e.g. output_dir is
    `<project>/terrain/`, style is `<project>/terrain_style.xml`). Returns
    the constant default if the file or material can't be parsed.
    """
    if output_dir is None:
        return _UNIFORM_RGBA
    style_path = output_dir.parent / "terrain_style.xml"
    if not style_path.exists():
        return _UNIFORM_RGBA
    try:
        tree = ET.parse(style_path)
        for mat in tree.iter("material"):
            if mat.get("name") != "terrain_mat":
                continue
            rgba_str = mat.get("rgba", "").strip()
            if not rgba_str:
                continue
            values = [float(v) for v in rgba_str.split()]
            if len(values) >= 4:
                return (values[0], values[1], values[2], values[3])
            if len(values) == 3:
                return (values[0], values[1], values[2], 1.0)
    except (ET.ParseError, ValueError):
        pass
    return _UNIFORM_RGBA


def _bind_uniform_texture(
    spec: mj.MjSpec,
    material,  # mj.MjsMaterial; not exported under that name in older builds
    texture: TextureConfig,
    output_dir: Optional[Path],
) -> None:
    """Register a 2D texture asset and bind it to `material` via the RGB role.

    The file path is resolved to absolute so MjSpec.compile() can validate
    it at build time; the post-processing regex in `emit_xml_include()` then
    rewrites all .png file paths to the portable `../terrain/<basename>`
    form that resolves correctly from the consuming model's directory.

    Resolution order for the texture path:
      1. Absolute path -> used as-is.
      2. `<output_dir>/../<file>` -> mirrors the regex's relative-path target.
      3. `<output_dir>/<file>` -> falls through if 2 doesn't exist.
    """
    raw = Path(texture.file)
    if raw.is_absolute():
        resolved = raw
    elif output_dir is not None:
        candidates = [
            (output_dir.parent / raw).resolve(),
            (output_dir / raw).resolve(),
        ]
        resolved = next((c for c in candidates if c.exists()), candidates[0])
    else:
        resolved = raw.resolve()

    if not resolved.exists():
        raise FileNotFoundError(
            f"Terrain texture file not found: {texture.file!r} "
            f"(resolved to {resolved}). Check `texture.file` in the JSON config."
        )

    # Normalize separators so the post-process regex in emit_xml_include
    # (which uses '/' as the path separator) matches and rewrites this path
    # to the portable `../terrain/<basename>` form. Without this on Windows
    # the absolute backslash path slips through verbatim and won't load
    # from the consuming model's directory.
    spec.add_texture(
        name=texture.name,
        type=mj.mjtTexture.mjTEXTURE_2D,
        file=str(resolved).replace("\\", "/"),
    )
    material.textures[mj.mjtTextureRole.mjTEXROLE_RGB] = texture.name
    material.texrepeat = list(texture.repeat)
    material.texuniform = bool(texture.texuniform)


def _bind_default_floor_texture(spec: mj.MjSpec, material) -> None:
    """Bind the default `matfloor` look: a built-in flat 2D texture with edge
    marks (a fine grid), mirroring the legacy terrain_style convention.  Used
    when the config supplies no explicit texture."""
    spec.add_texture(
        name="terrain_texfloor",
        type=mj.mjtTexture.mjTEXTURE_2D,
        builtin=mj.mjtBuiltin.mjBUILTIN_FLAT,
        width=128,
        height=128,
        rgb1=list(_MATFLOOR_RGB1),
        rgb2=list(_MATFLOOR_RGB1),
        mark=mj.mjtMark.mjMARK_EDGE,
        markrgb=list(_MATFLOOR_MARKRGB),
    )
    material.textures[mj.mjtTextureRole.mjTEXROLE_RGB] = "terrain_texfloor"
    material.texrepeat = [1, 1]
    material.texuniform = True


def build_terrain(
    config: TerrainConfig | UniformTerrainConfig,
    output_dir: Optional[Path] = None,
) -> mj.MjSpec:
    """Build a MuJoCo MjSpec from a terrain config and return it.

    Accepts either config form:
      * `TerrainConfig` -> the grid/tile path below (tiles + connectors +
        transparent backstop).
      * `UniformTerrainConfig` -> a single plane or heightfield surface via
        `_build_uniform` (see `uniform.py`).

    `output_dir` is where hfield-backed tiles (e.g. `rough`) write their
    PNG files. Required if any such tile is present in the config; ignored
    by purely-procedural tiles (flat, stairs, slope) and by the uniform path
    (its heightfield data is baked into the spec, not written to disk).
    `output_dir` is still used to resolve an optional `texture` in either
    form.

    Caller is responsible for either compiling (`spec.compile()`) or writing
    the XML (`emit_xml_include(spec)` for the include-friendly form).
    """
    if isinstance(config, UniformTerrainConfig):
        return _build_uniform(config, output_dir)

    spec = mj.MjSpec()
    spec.compiler.degree = False
    spec.modelname = config.terrain_name

    # Register palette materials in the generated spec so geoms can reference
    # them by name and pick up their reflectance / rgba properties.
    uniform_rgba = _read_uniform_rgba_from_style(output_dir)
    _register_palette_materials(spec, config, uniform_rgba, output_dir=output_dir)

    layouts = _compute_cell_layouts(config)

    # Resolve the final per-cell tile list: explicit `tiles` plus sampled
    # tiles for any cell not covered by an explicit entry (when a
    # randomization spec is supplied).
    resolved_tiles = _resolve_tiles(config)

    # Track per-cell base heights so connectors can match across cells.
    cell_results: dict[tuple[int, int], TileEmitResult] = {}

    # 1. Emit each placed tile.
    for tile_cfg in resolved_tiles:
        impl = lookup(tile_cfg.type)
        layout = layouts[(tile_cfg.row, tile_cfg.col)]
        appearance = _resolve_appearance(config, tile_cfg.type, impl.default_rgba, uniform_rgba)

        # Merge tile defaults with the user-specified params; user wins.
        # Composer-level kwargs (output_dir) override anything user-supplied
        # for those keys, since they're build-environment concerns, not
        # per-tile config.
        params = dict(impl.default_params)
        params.update(tile_cfg.params)
        params["output_dir"] = output_dir
        params["terrain_name"] = config.terrain_name

        result = impl.emit_fn(
            spec,
            origin_xyz=(layout.center_x, layout.center_y, 0.0),
            name=f"{tile_cfg.type}_r{tile_cfg.row}c{tile_cfg.col}",
            tile_size=config.grid.tile_size,
            rgba=appearance.rgba,
            material=appearance.material,
            **params,
        )
        cell_results[(tile_cfg.row, tile_cfg.col)] = result

    # 2. Emit edge connectors (between row-adjacent and column-adjacent cells).
    if config.border.width > 0:
        connector_appearance = _resolve_connector_appearance(config, uniform_rgba)
        _emit_edge_connectors(spec, config, layouts, cell_results, connector_appearance)
        _emit_corner_connectors(spec, config, layouts, cell_results, connector_appearance)

    # 3. Emit a backstop floor named `terrain` at the bottom of the grid.
    #    Two purposes: (a) satisfies model XMLs that declare explicit
    #    <contact><pair geom1="terrain" .../> entries (e.g. myoLeg26_*),
    #    (b) catches anything that falls through gaps or below tile bases.
    #    Rendered fully transparent (rgba alpha=0) since it's purely a
    #    contact-resolution surface.
    _emit_terrain_floor(spec, config, cell_results)

    return spec


# ---------------------------------------------------------------------------
# Uniform (single-surface) path


# The primary uniform geom is named `terrain` (the same name the grid path
# gives its backstop) so model XMLs that declare `<contact><pair
# geom1="terrain" .../>` resolve against the walkable surface directly. In
# the uniform path this geom IS the terrain, so no separate backstop is
# emitted.
_UNIFORM_GEOM_NAME = "terrain"
_UNIFORM_HFIELD_NAME = "terrain_hfield"


def _build_uniform(
    config: UniformTerrainConfig,
    output_dir: Optional[Path],
) -> mj.MjSpec:
    """Build a single-surface (plane or heightfield) terrain spec.

    Reuses the tile path's uniform-material machinery: one shared material
    (`myoassist_mat_uniform`) whose rgba tracks `terrain_style.xml`, plus an
    optional bound texture. The surface color is set explicitly on the geom
    so it overrides any inherited default-class rgba in the consuming model.
    """
    spec = mj.MjSpec()
    spec.compiler.degree = False
    spec.modelname = config.terrain_name

    # Horizon haze (fog) = the ground color, so an infinite plane fades into
    # its own color at the horizon instead of MuJoCo's default white.  compose
    # propagates this onto the consuming model's <visual>.
    spec.visual.rgba.haze = [*_MATFLOOR_RGB1, 1.0]

    material = spec.add_material(
        name=_UNIFORM_MATERIAL_NAME,
        rgba=[1.0, 1.0, 1.0, 1.0],
        specular=_UNIFORM_SPECULAR,
        shininess=_UNIFORM_SHININESS,
        reflectance=_MATFLOOR_REFLECTANCE,
    )
    if config.texture is not None:
        _bind_uniform_texture(spec, material, config.texture, output_dir)
    else:
        _bind_default_floor_texture(spec, material)

    appearance = _resolve_uniform_appearance(config)

    if config.terrain in ("flat", "slope"):
        _emit_uniform_plane(spec, config, appearance)
    else:  # 'random' | 'sinusoidal'
        _emit_uniform_hfield(spec, config, appearance)

    return spec


def _resolve_uniform_appearance(
    config: UniformTerrainConfig,
) -> _Appearance:
    """Pick the surface rgba.  Default is white so the material's texture (the
    `matfloor` grid) shows through unmodulated; a `palette` override tints it.
    Always uses the shared uniform material."""
    rgba: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    for key in (config.terrain, "uniform", "terrain"):
        if key in config.palette:
            override = config.palette[key]
            rgba = (override[0], override[1], override[2], override[3])
            break
    return _Appearance(rgba=_safe_rgba(rgba), material=_UNIFORM_MATERIAL_NAME)


def _emit_uniform_plane(
    spec: mj.MjSpec,
    config: UniformTerrainConfig,
    appearance: _Appearance,
) -> None:
    """Emit a single `mjGEOM_PLANE` through the origin.

    For `slope`, tilt the plane by `deg` about +y -- the axis perpendicular
    to the +x walking direction -- so the grade is constant and uphill in
    +x. The quaternion is a rotation about +y by `-deg` (radians): this maps
    the plane's local +z normal to (sin(deg), 0, cos(deg)), giving surface
    height z = tan(deg) * x (rising in the walking direction) while keeping
    the plane through the origin so the opening pose sits at z ~= 0.
    """
    quat = [1.0, 0.0, 0.0, 0.0]
    if config.terrain == "slope":
        beta = -math.radians(config.deg)
        quat = [math.cos(beta / 2.0), 0.0, math.sin(beta / 2.0), 0.0]

    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_PLANE,
        # Plane size = (half_x, half_y, grid_spacing).  half_x = half_y = 0
        # renders an infinite plane (matching the legacy ground); the third
        # value is the visual grid spacing.  A plane is analytically infinite
        # for collision regardless.
        "size": [0.0, 0.0, _PLANE_GRID_SPACING],
        "pos": [0.0, 0.0, 0.0],
        "quat": quat,
        "contype": 1,
        "conaffinity": 1,
    }
    if appearance.material is not None:
        geom_kwargs["material"] = appearance.material
    if appearance.rgba is not None:
        geom_kwargs["rgba"] = list(appearance.rgba)
    spec.worldbody.add_geom(name=_UNIFORM_GEOM_NAME, **geom_kwargs)


def _emit_uniform_hfield(
    spec: mj.MjSpec,
    config: UniformTerrainConfig,
    appearance: _Appearance,
) -> None:
    """Emit ONE heightfield geom for `random`/`sinusoidal` terrain.

    The elevation grid is generated in physical meters with a smooth safe
    zone flattening it toward 0 around the origin, then baked into the hfield
    via `userdata`. MuJoCo renormalizes `userdata` to [0, 1] using its own
    min/max and multiplies by `size[2]`; we set `size[2]` to the generated
    relief (max - min) so the emitted surface reproduces the physical heights
    exactly. The geom sits at z=0 with the surface minimum (the safe zone) at
    z=0, so a model resets flush with the ground.
    """
    n = config.resolution
    half = config.extent / 2.0

    if config.terrain == "random":
        field = uniform_gen.generate_random_field(
            nrow=n,
            ncol=n,
            half_x=half,
            half_y=half,
            amplitude=config.amplitude,
            safe_radius=config.safe_zone_radius,
            seed=config.seed,
        )
    else:  # 'sinusoidal'
        field = uniform_gen.generate_sinusoidal_field(
            nrow=n,
            ncol=n,
            half_x=half,
            half_y=half,
            amplitude=config.amplitude,
            period=config.period,
            safe_radius=config.safe_zone_radius,
        )

    dmin = float(field.min())
    dmax = float(field.max())
    relief = dmax - dmin
    # A perfectly flat field (relief 0) would give a degenerate hfield; fall
    # back to a nominal relief (the surface stays flat regardless).
    if relief < 1e-9:
        relief = max(config.amplitude, 1e-3)

    hfield = spec.add_hfield(
        name=_UNIFORM_HFIELD_NAME,
        nrow=n,
        ncol=n,
        size=[half, half, relief, config.base_depth],
    )
    # Shift so the minimum is 0; MuJoCo's renormalization (min->0, max->1)
    # then reproduces `field - dmin` after scaling by size[2]=relief.
    hfield.userdata = (field - dmin).reshape(-1).astype(np.float64)

    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_HFIELD,
        "hfieldname": _UNIFORM_HFIELD_NAME,
        "pos": [0.0, 0.0, 0.0],
        "contype": 1,
        "conaffinity": 1,
    }
    if appearance.material is not None:
        geom_kwargs["material"] = appearance.material
    if appearance.rgba is not None:
        geom_kwargs["rgba"] = list(appearance.rgba)
    spec.worldbody.add_geom(name=_UNIFORM_GEOM_NAME, **geom_kwargs)


# ---------------------------------------------------------------------------
# Layout


def _resolve_tiles(config: TerrainConfig) -> list[TileConfig]:
    """Combine explicit `tiles` with sampled tiles for any uncovered cell.

    Explicit placements take precedence; randomization fills the rest.
    Returns a flat list of TileConfig in row-major order.
    """
    occupied: set[tuple[int, int]] = {(t.row, t.col) for t in config.tiles}
    out: list[TileConfig] = list(config.tiles)

    if config.randomization is None:
        return out

    rs = config.randomization
    # Accept only registered tile types in weights.
    types: list[str] = []
    weights_arr: list[float] = []
    for type_name, w in rs.weights.items():
        if w <= 0:
            continue
        if type_name not in REGISTRY:
            raise ValueError(
                f"randomization.weights references unknown tile type {type_name!r}; "
                f"registered types: {sorted(REGISTRY)}"
            )
        types.append(type_name)
        weights_arr.append(float(w))
    if not types:
        raise ValueError("randomization.weights has no positive entries")
    weights = np.asarray(weights_arr, dtype=float)
    weights /= weights.sum()

    rng = np.random.default_rng(int(rs.seed))

    for r in range(config.grid.rows):
        for c in range(config.grid.cols):
            if (r, c) in occupied:
                continue
            chosen_type = str(rng.choice(types, p=weights))
            params = _sample_tile_params(rng, chosen_type, rs.param_ranges.get(chosen_type, {}))
            out.append(TileConfig(row=r, col=c, type=chosen_type, params=params))

    # Re-sort row-major so debug output is predictable.
    out.sort(key=lambda t: (t.row, t.col))
    return out


def _sample_tile_params(
    rng: np.random.Generator,
    type_name: str,
    user_ranges: dict[str, list[float]],
) -> dict:
    """Build a randomized params dict for one tile sample.

    Each entry in user_ranges (or a tile's built-in PARAM_RANGES /
    default_categorical) can be either:
      - [lo, hi] of two numbers -- uniform numeric sample (int vs float
        determined by the param's default)
      - a list of strings/bools -- uniform categorical sample
    A degenerate numeric range [v, v] fixes the param at v. Params not
    appearing in either ranges or categorical defaults fall through to
    the tile's DEFAULT_PARAMS unchanged.
    """
    impl = REGISTRY[type_name]
    params = dict(impl.default_params)

    # Built-in numeric ranges.
    for param_name, (lo, hi) in impl.param_ranges.items():
        if param_name in user_ranges:
            continue
        params[param_name] = _sample_numeric(rng, lo, hi, params.get(param_name))

    # Built-in categorical choices.
    for param_name, choices in impl.default_categorical.items():
        if param_name in user_ranges or not choices:
            continue
        params[param_name] = _sample_categorical(rng, choices)

    # User overrides (numeric range, categorical list, or fixed via [v, v]).
    for param_name, spec in user_ranges.items():
        params[param_name] = _sample_user_spec(
            rng, spec, type_name, param_name, params.get(param_name)
        )

    return params


def _is_numeric_range(spec: list) -> bool:
    return len(spec) == 2 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in spec
    )


def _sample_user_spec(rng, spec, type_name: str, param_name: str, default_value):
    if not isinstance(spec, list):
        raise ValueError(
            f"randomization.param_ranges[{type_name!r}][{param_name!r}] must be a list, "
            f"got {type(spec).__name__}"
        )
    if len(spec) == 0:
        raise ValueError(
            f"randomization.param_ranges[{type_name!r}][{param_name!r}] cannot be empty"
        )
    if _is_numeric_range(spec):
        return _sample_numeric(rng, float(spec[0]), float(spec[1]), default_value)
    return _sample_categorical(rng, spec)


def _sample_categorical(rng: np.random.Generator, choices: list):
    return choices[int(rng.integers(0, len(choices)))]


def _sample_numeric(rng: np.random.Generator, lo: float, hi: float, default_value):
    """Sample a uniform value, returning int when the param's default is int."""
    if isinstance(default_value, int) and not isinstance(default_value, bool):
        if hi < lo:
            raise ValueError(f"sample range hi ({hi}) < lo ({lo})")
        return int(rng.integers(int(lo), int(hi) + 1))
    return float(rng.uniform(float(lo), float(hi)))


def _compute_cell_layouts(config: TerrainConfig) -> dict[tuple[int, int], _CellLayout]:
    tw, tl = config.grid.tile_size
    bw = config.border.width
    rows, cols = config.grid.rows, config.grid.cols

    total_w = cols * tw + (cols - 1) * bw
    total_l = rows * tl + (rows - 1) * bw

    x_first = -total_w / 2 + tw / 2
    y_first = -total_l / 2 + tl / 2

    layouts: dict[tuple[int, int], _CellLayout] = {}
    for r in range(rows):
        for c in range(cols):
            layouts[(r, c)] = _CellLayout(
                row=r,
                col=c,
                center_x=x_first + c * (tw + bw),
                center_y=y_first + r * (tl + bw),
            )
    return layouts


# ---------------------------------------------------------------------------
# Palette / appearance


def _palette_material_name(type_name: str) -> str:
    return f"{_PALETTE_MATERIAL_PREFIX}{type_name}"


# MjSpec drops rgba attributes from emitted XML when they exactly match
# MuJoCo's geom default (0.5, 0.5, 0.5, 1). When that happens, the geom
# inherits its consuming model's default-class rgba at compile time --
# which in myoLeg26's class="main" is tan 0.8 0.6 0.4. Perturb by a
# floating-point hair so MjSpec keeps the attribute. The visual is
# indistinguishable.
_MJSPEC_DEFAULT_GEOM_RGBA = (0.5, 0.5, 0.5, 1.0)


def _safe_rgba(rgba: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if tuple(rgba) == _MJSPEC_DEFAULT_GEOM_RGBA:
        return (rgba[0] - 1e-6, rgba[1], rgba[2], rgba[3])
    return tuple(rgba)


def _register_palette_materials(
    spec: mj.MjSpec,
    config: TerrainConfig,
    uniform_rgba: tuple[float, float, float, float] = _UNIFORM_RGBA,
    output_dir: Optional[Path] = None,
) -> None:
    """For diverse/custom modes, declare a per-tile-type material in the spec
    so geoms can reference it. Each material carries that tile's rgba (with
    user palette overrides) and specular/shininess from its TileImpl record.
    In uniform mode, register a single shared material whose rgba is read
    from the user's terrain_style.xml so manual edits to the style file flow
    through to generated terrains automatically.
    """
    if config.palette_preset == "uniform":
        # Important: the material's rgba is intentionally a SENTINEL (white)
        # different from any color we'd actually use on geoms. MjSpec.to_xml()
        # drops a geom's `rgba` attribute when it matches the material's rgba
        # exactly (an internal optimization), and a geom that ends up with no
        # rgba in the XML falls back to its class default at MuJoCo compile
        # time -- which in the consuming model (myoLeg26's class="main") is
        # tan 0.8 0.6 0.4. Keeping the material rgba distinct guarantees the
        # geom rgba sticks.
        material = spec.add_material(
            name=_UNIFORM_MATERIAL_NAME,
            rgba=[1.0, 1.0, 1.0, 1.0],
            specular=_UNIFORM_SPECULAR,
            shininess=_UNIFORM_SHININESS,
        )
        if config.texture is not None:
            _bind_uniform_texture(spec, material, config.texture, output_dir)
        return

    # All palette materials use a sentinel rgba (white) so MjSpec doesn't
    # collapse matching geom rgbas during XML emission. Each geom carries
    # its actual color via its own rgba attribute, while the material
    # provides specular/shininess. See the uniform-mode comment for context.
    for type_name, impl in REGISTRY.items():
        spec.add_material(
            name=_palette_material_name(type_name),
            rgba=[1.0, 1.0, 1.0, 1.0],
            specular=impl.default_specular,
            shininess=impl.default_shininess,
        )

    spec.add_material(
        name=_palette_material_name("connector"),
        rgba=[1.0, 1.0, 1.0, 1.0],
        specular=_CONNECTOR_SPECULAR,
        shininess=_CONNECTOR_SHININESS,
    )


def _resolve_appearance(
    config: TerrainConfig,
    type_name: str,
    tile_default_rgba: tuple[float, float, float, float],
    uniform_rgba: tuple[float, float, float, float] = _UNIFORM_RGBA,
) -> _Appearance:
    # Determine the rgba for this tile type. Set explicitly on the geom so
    # we override any inherited rgba from the consuming model's default
    # geom class (e.g. myoLeg26_*'s class="main" sets rgba="0.8 0.6 0.4 1",
    # which would otherwise show through every terrain geom because per-geom
    # rgba beats material rgba in MuJoCo).
    if type_name in config.palette:
        rgba = tuple(config.palette[type_name])
    else:
        rgba = tile_default_rgba

    if config.palette_preset == "uniform":
        return _Appearance(rgba=_safe_rgba(uniform_rgba), material=_UNIFORM_MATERIAL_NAME)
    return _Appearance(rgba=_safe_rgba(rgba), material=_palette_material_name(type_name))


def _resolve_connector_appearance(
    config: TerrainConfig,
    uniform_rgba: tuple[float, float, float, float] = _UNIFORM_RGBA,
) -> _Appearance:
    if config.palette_preset == "uniform":
        return _Appearance(rgba=_safe_rgba(uniform_rgba), material=_UNIFORM_MATERIAL_NAME)
    if "connector" in config.palette:
        connector_rgba = tuple(config.palette["connector"])
    else:
        connector_rgba = _CONNECTOR_DEFAULT_RGBA
    return _Appearance(
        rgba=_safe_rgba(connector_rgba),
        material=_palette_material_name("connector"),
    )


# ---------------------------------------------------------------------------
# Connectors


# Connector geoms span from BASELINE_Z up to the negotiated top height, so
# their bottoms align with tile bottoms and adjacent height differences read
# as clean step risers instead of floating shelves.


def _box_z_span(top_z: float) -> tuple[float, float]:
    """Return (center_z, half_z) for a box spanning [BASELINE_Z, top_z]."""
    if top_z <= BASELINE_Z:
        raise ValueError(
            f"box top_z={top_z:.3f} must be > BASELINE_Z={BASELINE_Z:.3f}"
        )
    half_z = (top_z - BASELINE_Z) / 2
    center_z = (top_z + BASELINE_Z) / 2
    return center_z, half_z


def _emit_edge_connectors(
    spec: mj.MjSpec,
    config: TerrainConfig,
    layouts: dict[tuple[int, int], _CellLayout],
    cell_results: dict[tuple[int, int], TileEmitResult],
    appearance: _Appearance,
) -> None:
    tw, tl = config.grid.tile_size
    bw = config.border.width
    rows, cols = config.grid.rows, config.grid.cols

    # East-west edges (between col c and col c+1, for each row).
    for r in range(rows):
        for c in range(cols - 1):
            if (r, c) not in cell_results or (r, c + 1) not in cell_results:
                continue
            base = _match_heights(
                config.border.match_mode,
                [cell_results[(r, c)].base_height, cell_results[(r, c + 1)].base_height],
            )
            cx = (layouts[(r, c)].center_x + layouts[(r, c + 1)].center_x) / 2
            cy = layouts[(r, c)].center_y
            center_z, half_z = _box_z_span(base)
            _emit_flat_box(
                spec,
                name=f"connector_ew_r{r}c{c}",
                center_xyz=(cx, cy, center_z),
                half_size=(bw / 2, tl / 2, half_z),
                appearance=appearance,
            )

    # North-south edges (between row r and row r+1, for each col).
    for r in range(rows - 1):
        for c in range(cols):
            if (r, c) not in cell_results or (r + 1, c) not in cell_results:
                continue
            base = _match_heights(
                config.border.match_mode,
                [cell_results[(r, c)].base_height, cell_results[(r + 1, c)].base_height],
            )
            cx = layouts[(r, c)].center_x
            cy = (layouts[(r, c)].center_y + layouts[(r + 1, c)].center_y) / 2
            center_z, half_z = _box_z_span(base)
            _emit_flat_box(
                spec,
                name=f"connector_ns_r{r}c{c}",
                center_xyz=(cx, cy, center_z),
                half_size=(tw / 2, bw / 2, half_z),
                appearance=appearance,
            )


def _emit_corner_connectors(
    spec: mj.MjSpec,
    config: TerrainConfig,
    layouts: dict[tuple[int, int], _CellLayout],
    cell_results: dict[tuple[int, int], TileEmitResult],
    appearance: _Appearance,
) -> None:
    bw = config.border.width
    rows, cols = config.grid.rows, config.grid.cols
    for r in range(rows - 1):
        for c in range(cols - 1):
            quad = [(r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)]
            if any(cell not in cell_results for cell in quad):
                continue
            base = _match_heights(
                config.border.match_mode,
                [cell_results[cell].base_height for cell in quad],
            )
            cx = (layouts[(r, c)].center_x + layouts[(r, c + 1)].center_x) / 2
            cy = (layouts[(r, c)].center_y + layouts[(r + 1, c)].center_y) / 2
            center_z, half_z = _box_z_span(base)
            _emit_flat_box(
                spec,
                name=f"connector_corner_r{r}c{c}",
                center_xyz=(cx, cy, center_z),
                half_size=(bw / 2, bw / 2, half_z),
                appearance=appearance,
            )


def _emit_terrain_floor(
    spec: mj.MjSpec,
    config: TerrainConfig,
    cell_results: dict[tuple[int, int], TileEmitResult],
) -> None:
    """Emit the contract `terrain` geom -- an invisible backstop plane.

    Purpose is purely contact-resolution: model XMLs that declare
    `<contact><pair geom1="terrain" .../>` need a geom by that exact name to
    compile. Rendered transparent (alpha=0) so it doesn't appear in the
    visualizer. Placed deep enough below all tiles that it can also catch
    fall-throughs without interfering with tile geometry.
    """
    tw, tl = config.grid.tile_size
    bw = config.border.width
    rows, cols = config.grid.rows, config.grid.cols

    total_w = cols * tw + max(cols - 1, 0) * bw
    total_l = rows * tl + max(rows - 1, 0) * bw

    # All tile and connector bottoms sit at BASELINE_Z; place the backstop
    # one meter below that so it never intersects authored tile geometry.
    floor_top_z = BASELINE_Z - 1.0
    floor_thickness = 0.2

    transparent = _Appearance(rgba=(0.0, 0.0, 0.0, 0.0))
    _emit_flat_box(
        spec,
        name="terrain",
        center_xyz=(0.0, 0.0, floor_top_z - floor_thickness / 2),
        half_size=(total_w / 2, total_l / 2, floor_thickness / 2),
        appearance=transparent,
    )


def _emit_flat_box(
    spec: mj.MjSpec,
    *,
    name: str,
    center_xyz: tuple[float, float, float],
    half_size: tuple[float, float, float],
    appearance: _Appearance,
    geom_name: str | None = None,
) -> None:
    """Emit a static box geom directly on worldbody (no body wrapper)."""
    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_BOX,
        "size": list(half_size),
        "pos": list(center_xyz),
        "contype": 1,
        "conaffinity": 1,
    }
    if appearance.material is not None:
        geom_kwargs["material"] = appearance.material
    if appearance.rgba is not None:
        geom_kwargs["rgba"] = list(appearance.rgba)
    spec.worldbody.add_geom(name=geom_name or name, **geom_kwargs)


def _match_heights(mode: str, heights: list[float]) -> float:
    if mode == "min":
        return min(heights)
    if mode == "max":
        return max(heights)
    if mode == "mean":
        return sum(heights) / len(heights)
    raise ValueError(f"Unknown match_mode {mode!r}")


# ---------------------------------------------------------------------------
# XML emission


def emit_xml_include(
    spec: mj.MjSpec,
    *,
    hfield_relpath_prefix: str = "../terrain",
    texture_relpath_prefix: str = "..",
) -> str:
    """Convert spec.to_xml() output into a `<mujocoinclude>`-rooted fragment.

    MjSpec.to_xml() emits a complete <mujoco>...</mujoco> document. For our
    Option B file layout we want a `<mujocoinclude>` fragment containing only
    the asset declarations and the worldbody contents (other top-level
    elements like <compiler>, <option>, <visual> belong in the consuming
    model file, not in a terrain include).

    File-bearing assets (hfield PNGs, texture PNGs) are registered against
    MjSpec by ABSOLUTE path so that MjSpec.compile() can validate them at
    build time. The absolute path is not portable -- MuJoCo's loader resolves
    relative paths against the TOP-LEVEL model file's directory, so the
    emitted XML needs paths anchored relative to that. We rewrite each
    asset's `file=` attribute based on its element type:

      * `<hfield>`  -- always written by the composer into the terrain
                       library `output_dir/`. The emitted path resolves to
                       `{hfield_relpath_prefix}/<basename>` (default
                       `../terrain/<basename>`, which is correct when the
                       consumer model lives one directory below the project
                       root).

      * `<texture>` -- user-supplied asset; the file typically lives at
                       project root next to `terrain_style.xml`. The
                       emitted path resolves to
                       `{texture_relpath_prefix}/<basename>` (default
                       `../<basename>`, i.e. one level up from the model).

    Both prefixes are configurable for non-standard layouts. For textures
    in subdirectories, supply an absolute or pre-resolved path on the
    TextureConfig and override `texture_relpath_prefix` accordingly.
    """
    src = spec.to_xml()
    src_root = ET.fromstring(src)

    out_root = ET.Element("mujocoinclude")
    for child in src_root:
        if child.tag in {"asset", "worldbody"}:
            out_root.append(child)

    # Rewrite asset file paths to portable relative ones. Walk every element
    # under the assembled tree so the rule applies regardless of nesting.
    type_to_prefix = {
        "hfield": hfield_relpath_prefix,
        "texture": texture_relpath_prefix,
    }
    for elem in out_root.iter():
        prefix = type_to_prefix.get(elem.tag)
        if prefix is None:
            continue
        file_attr = elem.get("file")
        if not file_attr:
            continue
        basename = file_attr.replace("\\", "/").rsplit("/", 1)[-1]
        elem.set("file", f"{prefix}/{basename}")

    ET.indent(out_root, space="    ")
    return ET.tostring(out_root, encoding="unicode")
