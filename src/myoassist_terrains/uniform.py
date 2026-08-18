"""Uniform-surface terrain generation (single plane or one heightfield).

Distinct from the grid/tile composer path (`composer.build_terrain` over a
`TerrainConfig`), which tiles finite box/hfield cells across a grid. A
*uniform* terrain is a single continuous walkable surface:

  - ``flat`` / ``slope`` -> one ``mjGEOM_PLANE`` (slope = the plane tilted a
    constant grade about +y, the axis perpendicular to the +x walking
    direction; the plane passes through the origin so the opening pose sits
    at z ~= 0).
  - ``random`` / ``sinusoidal`` -> ONE heightfield geom covering a generous
    walkable extent, with a smooth "safe zone" near the origin where the
    surface is flattened toward 0 so a model does not fall on reset.

This module holds only the pure-numpy heightfield generation. Geom emission,
material/texture styling, and the ``MjSpec`` assembly live in
``composer._build_uniform`` so the uniform path reuses the same palette /
material machinery as the tile path.

The generation is ported from the retired runtime ``HfieldManager`` (which
mutated a pre-declared hfield's ``data`` in place at reset). Here we generate
the elevation grid at BUILD time; the composer bakes it into the returned
``MjSpec`` via the hfield's ``userdata`` (MuJoCo renormalizes ``userdata`` to
[0, 1] and scales by ``size[2]``, so the composer sets ``size[2]`` to the
generated relief to reproduce the physical heights faithfully).
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from myoassist_terrains import hfield


def _smoothstep(t: np.ndarray) -> np.ndarray:
    """Hermite smoothstep on an array already clamped to [0, 1]."""
    return t * t * (3.0 - 2.0 * t)


def safe_zone_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    radius: float,
) -> np.ndarray:
    """Smooth radial mask: 0 at the origin, rising to 1 at ``radius``.

    Multiplying a heightfield by this mask flattens a disc of the given
    radius around the origin (the reset "safe zone") so the surface is ~0
    there and the model does not spawn on a bump or in a pit. ``radius <= 0``
    disables the safe zone (returns all ones).
    """
    if radius <= 0.0:
        return np.ones_like(xx)
    dist = np.sqrt(xx * xx + yy * yy)
    t = np.clip(dist / radius, 0.0, 1.0)
    return _smoothstep(t)


def _grid(
    nrow: int,
    ncol: int,
    half_x: float,
    half_y: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (xx, yy) physical-coordinate grids of shape (nrow, ncol).

    MuJoCo stores hfield data row-major with ``ncol`` along +x and ``nrow``
    along +y, so columns index x and rows index y.
    """
    xs = np.linspace(-half_x, half_x, ncol)
    ys = np.linspace(-half_y, half_y, nrow)
    xx, yy = np.meshgrid(xs, ys)  # indexing='xy' -> shape (nrow, ncol)
    return xx, yy


def generate_random_field(
    nrow: int,
    ncol: int,
    half_x: float,
    half_y: float,
    amplitude: float,
    safe_radius: float,
    seed: int,
) -> np.ndarray:
    """Per-cell uniform noise in [0, amplitude], flattened near the origin.

    Ports the retired generator's ``uniform(0, amplitude)`` fill plus the
    safe-zone mask.
    """
    rng = np.random.default_rng(int(seed))
    field = rng.uniform(0.0, float(amplitude), size=(nrow, ncol))
    xx, yy = _grid(nrow, ncol, half_x, half_y)
    return field * safe_zone_mask(xx, yy, float(safe_radius))


def generate_sinusoidal_field(
    nrow: int,
    ncol: int,
    half_x: float,
    half_y: float,
    amplitude: float,
    period: float,
    safe_radius: float,
) -> np.ndarray:
    """A single sinusoid along the +x walking axis, flattened near the origin.

    Surface = ``amplitude * (1 + sin(2*pi*x/period)) / 2``, i.e. a wave whose
    troughs sit at 0 and crests at ``amplitude`` (relief == ``amplitude``).
    The single-axis ``amplitude`` + ``period`` API is a deliberate
    simplification of the retired generator's repeatable
    ``amplitude_row period_row amplitude_col period_col`` sum-of-sines; it
    keeps the config clean and stays extensible to a cross-axis term later.
    """
    xx, yy = _grid(nrow, ncol, half_x, half_y)
    field = float(amplitude) * 0.5 * (1.0 + np.sin(2.0 * np.pi * xx / float(period)))
    return field * safe_zone_mask(xx, yy, float(safe_radius))


# ---------------------------------------------------------------------------
# Elevation field + surface height
#
# `composer._emit_uniform_hfield` and `surface_height` below both go through
# `elevation_field`, so the height reported for a uniform terrain cannot drift
# from the heightfield that was emitted.


@lru_cache(maxsize=32)
def _cached_field(
    terrain: str,
    nrow: int,
    ncol: int,
    half_x: float,
    half_y: float,
    amplitude: float,
    period: float,
    safe_radius: float,
    seed: int,
) -> tuple[np.ndarray, float, float]:
    if terrain == "random":
        field = generate_random_field(
            nrow=nrow,
            ncol=ncol,
            half_x=half_x,
            half_y=half_y,
            amplitude=amplitude,
            safe_radius=safe_radius,
            seed=seed,
        )
    else:
        field = generate_sinusoidal_field(
            nrow=nrow,
            ncol=ncol,
            half_x=half_x,
            half_y=half_y,
            amplitude=amplitude,
            period=period,
            safe_radius=safe_radius,
        )
    dmin = float(field.min())
    relief = float(field.max()) - dmin
    # A perfectly flat field would give a degenerate hfield; fall back to a
    # nominal relief (the surface stays flat regardless).
    if relief < 1e-9:
        relief = max(amplitude, 1e-3)
    return field, dmin, relief


def elevation_field(config) -> tuple[np.ndarray, float, float]:
    """Return (field, dmin, relief) for a heightfield-backed uniform terrain.

    `field` is in physical meters. The composer bakes `field - dmin` into the
    hfield's userdata with `size[2] = relief`, and MuJoCo's renormalization then
    reproduces `field - dmin` exactly, so the emitted surface height at a point
    is `field - dmin`.
    """
    if config.terrain not in ("random", "sinusoidal"):
        raise ValueError(f"elevation_field is only defined for random/sinusoidal terrain, got {config.terrain!r}")
    half = config.extent / 2.0
    return _cached_field(
        config.terrain,
        config.resolution,
        config.resolution,
        half,
        half,
        float(config.amplitude),
        float(config.period),
        float(config.safe_zone_radius),
        int(config.seed),
    )


def surface_height(config, x: float, y: float) -> float:
    """Walkable surface height of a uniform terrain at world (x, y).

    `flat` is z=0. `slope` is the plane through the origin tilted about +y, so
    z = tan(deg) * x, rising in the +x walking direction. `random` and
    `sinusoidal` sample the emitted elevation field bilinearly.
    """
    if config.terrain == "flat":
        return 0.0
    if config.terrain == "slope":
        return float(math.tan(math.radians(config.deg)) * x)

    field, dmin, _relief = elevation_field(config)
    nrow, ncol = field.shape
    half = config.extent / 2.0
    # `_grid` lays the field out with columns along +x and rows along +y.
    u = ((x + half) / (2.0 * half)) * (ncol - 1)
    v = ((y + half) / (2.0 * half)) * (nrow - 1)
    return float(hfield.sample(field, u, v) - dmin)
