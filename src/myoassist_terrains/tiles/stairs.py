"""`stairs` tile: Colab-style mirrored staircase.

Layout along the chosen axis (default `y`):

    landing  up steps      peak       down steps  landing
    |______|//|//|//|//|________|\\|\\|\\|\\|______|
                \\               /
                 \\_ peak_width _/

All four edges of the tile sit at `base_height` (flat-at-base contract). When
`step_width` is left unset it is auto-computed to leave exactly one tread of
flat landing at each end, so the first riser never lands flush with the tile
edge -- a flush riser would put a `step_height` wall against the connector,
which is what the contract exists to prevent.

Stairs rise from base_height by `n_steps * step_height`, plateau across
`peak_width`, then mirror back down to base_height. v1 only supports the
`mirror` return mode; ramp-back is deferred to v2.

Step geometry: each step is its own box that extends from BASELINE_Z up
to its tread height. The base slab beneath the entire tile provides the
flat margin between the stair span and the tile edges plus the floor under
the steps; step boxes overlap the base inside the stair span (rendering
picks the topmost surface). For `inverted`, the base is emitted as a
four-sided frame instead, so the pit is open from above while the perimeter
stays closed at `base_height`.
"""

from __future__ import annotations

import mujoco as mj

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.30, 0.50, 0.85, 1.0)  # blue

DEFAULT_PARAMS: dict = {
    "step_height": 0.15,
    "step_width": None,  # None => auto-compute, leaving one tread of landing per end
    "n_steps": 6,
    "axis": "y",
    "peak_width": 0.40,
    "return_mode": "mirror",
    "base_height": 0.0,
    "cross_ratio": 0.90,  # active region covers 90% of cross axis; remainder is flat base margin
    "inverted": False,  # True => steps descend into a pit instead of rising to a peak
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "step_height": (0.08, 0.25),
    # step_width is intentionally NOT randomized — leaving it unset triggers
    # auto-fill so stairs span the tile minus one tread of landing per end,
    # regardless of n_steps.
    "n_steps": (3, 12),
    "peak_width": (0.20, 0.50),
    # base_height intentionally not randomized — see flat.py for the rationale.
}

PARAM_DOCS: dict[str, str] = {
    "step_height": "Riser height per step.",
    "step_width": "Tread depth. None auto-fits all n_steps, leaving one tread of landing at each end.",
    "n_steps": "Number of risers from base to peak.",
    "axis": "Axis the staircase progresses along, so you cross the steps travelling along it.",
    "peak_width": "Width of the flat plateau at the top.",
    "return_mode": "How the descending half is built. v1 supports 'mirror' only.",
    "cross_ratio": "Fraction of the perpendicular axis covered by tread; the remainder is flat base margin.",
    "inverted": "If True, the steps descend into a pit and mirror back up.",
    "base_height": "z-coordinate of the tile's flat-edge base.",
}

SPEED_SCALE = 0.55


def _geometry(
    tile_size: tuple[float, float],
    axis: str,
    n_steps: int,
    step_width: float | None,
    peak_width: float,
    cross_ratio: float,
):
    """Axis mapping and span arithmetic shared by `emit` and `surface_height`.

    Auto-fill reserves one tread at each end: solving
    `2*n*sw + peak + 2*sw == long` gives `sw = (long - peak) / (2n + 2)`, so the
    landing scales with `n_steps` and `peak_width` without a separate parameter.
    """
    long_idx, cross_idx = (1, 0) if axis == "y" else (0, 1)
    long_total = tile_size[long_idx]
    cross_total = tile_size[cross_idx]
    if step_width is None:
        step_width = (long_total - peak_width) / (2 * n_steps + 2)
    step_width = float(step_width)
    stair_span = 2 * n_steps * step_width + peak_width
    long_margin = (long_total - stair_span) / 2.0
    cross_half = cross_total * cross_ratio / 2
    return long_idx, cross_idx, long_total, cross_total, step_width, stair_span, long_margin, cross_half


def surface_height(
    local_x: float,
    local_y: float,
    *,
    tile_size: tuple[float, float],
    step_height: float = 0.15,
    step_width: float | None = None,
    n_steps: int = 6,
    axis: str = "y",
    peak_width: float = 0.40,
    base_height: float = 0.0,
    cross_ratio: float = 0.90,
    inverted: bool = False,
    **_,
) -> float:
    """Walkable surface height at a tile-local (x, y).

    Outside the stair span (the landings) and outside the cross-axis active
    region, the base slab is exposed at `base_height`. Inside, step *i* spans
    `[i*sw, (i+1)*sw)` from the near end of the span with its tread at
    `base + (i+1)*step_height`, so the level is `floor(u / sw) + 1`, clamped to
    `n_steps` on the peak plateau.
    """
    (long_idx, _cross_idx, _long_total, _cross_total, step_width, stair_span, long_margin, cross_half) = _geometry(
        tile_size, axis, int(n_steps), step_width, float(peak_width), float(cross_ratio)
    )
    long_local = local_y if long_idx == 1 else local_x
    cross_local = local_x if long_idx == 1 else local_y

    if abs(cross_local) > cross_half:
        return float(base_height)  # flat base margin beside the tread

    # Distance from the low end of the stair span, which starts one landing in.
    span_local = long_local + stair_span / 2.0
    if span_local < 0.0 or span_local > stair_span:
        return float(base_height)  # on a landing

    from_near_end = min(span_local, stair_span - span_local)
    if from_near_end >= n_steps * step_width:
        level = int(n_steps)  # on the peak plateau
    else:
        level = int(from_near_end // step_width) + 1
    excursion = level * float(step_height)
    if inverted:
        excursion = -excursion
    return float(base_height + excursion)


def emit(
    spec: mj.MjSpec,
    origin_xyz: tuple[float, float, float],
    name: str,
    *,
    tile_size: tuple[float, float],
    rgba: tuple[float, float, float, float] | None = None,
    material: str | None = None,
    step_height: float = 0.15,
    step_width: float | None = None,
    n_steps: int = 6,
    axis: str = "y",
    peak_width: float = 0.40,
    return_mode: str = "mirror",
    base_height: float = 0.0,
    cross_ratio: float = 0.90,
    inverted: bool = False,
) -> TileEmitResult:
    if axis not in ("x", "y"):
        raise ValueError(f"stairs.axis must be 'x' or 'y', got {axis!r}")
    if return_mode != "mirror":
        raise NotImplementedError(f"stairs.return_mode={return_mode!r} not in v1; only 'mirror' supported.")
    if n_steps < 1:
        raise ValueError(f"stairs.n_steps must be >= 1, got {n_steps}")
    if step_height <= 0 or peak_width <= 0:
        raise ValueError("stairs step_height and peak_width must be positive")
    if step_width is not None and step_width <= 0:
        raise ValueError(f"stairs.step_width must be positive (got {step_width})")
    if not (0.0 < cross_ratio <= 1.0):
        raise ValueError(f"stairs.cross_ratio must satisfy 0 < ratio <= 1, got {cross_ratio}")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(f"stairs '{name}': base top z={base_top_z:.3f} <= BASELINE_Z={BASELINE_Z:.3f}; increase base_height.")

    (long_idx, cross_idx, long_total, cross_total, step_width, stair_span, long_margin, cross_half) = _geometry(
        tile_size, axis, n_steps, step_width, peak_width, cross_ratio
    )

    if step_width <= 0:
        raise ValueError(
            f"stairs '{name}': peak_width ({peak_width:.3f} m) >= tile long axis "
            f"({long_total:.3f} m); reduce peak_width or specify step_width explicitly."
        )
    if stair_span > long_total + 1e-9:
        raise ValueError(
            f"stairs '{name}': total stair span {stair_span:.3f} m exceeds tile_size along "
            f"axis={axis} ({long_total:.3f} m). Reduce n_steps, step_width, or peak_width."
        )

    origin_x, origin_y = origin_xyz[0], origin_xyz[1]

    # Static terrain: emit geoms directly on worldbody. World positions
    # are computed by adding the tile origin to per-geom local offsets.
    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_BOX,
        "contype": 1,
        "conaffinity": 1,
    }
    if material is not None:
        geom_kwargs["material"] = material
    if rgba is not None:
        geom_kwargs["rgba"] = list(rgba)

    # 1. Base — for upright stairs, a full-tile slab at base_height. For
    #    inverted stairs, a four-sided frame: the cross-axis margins plus the
    #    long-axis landings, so the pit is open from above while the perimeter
    #    stays closed at base_height (the flat-at-base contract).
    base_half_z = (base_top_z - BASELINE_Z) / 2
    base_center_z = (base_top_z + BASELINE_Z) / 2
    if not inverted:
        spec.worldbody.add_geom(
            name=f"{name}_base",
            size=[tile_size[0] / 2, tile_size[1] / 2, base_half_z],
            pos=[origin_x, origin_y, base_center_z],
            **geom_kwargs,
        )
    else:
        cross_margin_half = (cross_total - cross_total * cross_ratio) / 2 / 2
        if cross_margin_half > 0:
            # Cross-axis strips, spanning the full long axis.
            for side, sign in (("a", -1), ("b", +1)):
                pos = [origin_x, origin_y, base_center_z]
                size = [0.0, 0.0, base_half_z]
                pos[cross_idx] += sign * (cross_total / 2 - cross_margin_half)
                size[cross_idx] = cross_margin_half
                size[long_idx] = tile_size[long_idx] / 2
                spec.worldbody.add_geom(name=f"{name}_base_{side}", size=size, pos=pos, **geom_kwargs)
        if long_margin > 1e-9:
            # Long-axis landings, inset across so they do not double-cover the
            # corners already carried by the cross strips.
            for side, sign in (("c", -1), ("d", +1)):
                pos = [origin_x, origin_y, base_center_z]
                size = [0.0, 0.0, base_half_z]
                pos[long_idx] += sign * (long_total / 2 - long_margin / 2)
                size[long_idx] = long_margin / 2
                size[cross_idx] = cross_half
                spec.worldbody.add_geom(name=f"{name}_base_{side}", size=size, pos=pos, **geom_kwargs)

    # Step direction sign: +1 = up to a peak, -1 = down into a pit.
    step_sign = -1.0 if inverted else +1.0

    # Sanity-check that the deepest pit floor stays above BASELINE_Z.
    deepest_top = base_top_z + step_sign * n_steps * step_height
    if deepest_top <= BASELINE_Z:
        raise ValueError(
            f"stairs '{name}' inverted: pit floor z={deepest_top:.3f} would land at or "
            f"below BASELINE_Z={BASELINE_Z:.3f}. Reduce n_steps × step_height, raise "
            f"base_height, or accept that this descent depth isn't supported."
        )

    def _emit_step(suffix: str, long_center: float, long_half: float, top_z: float) -> None:
        pos = [origin_x, origin_y, (top_z + BASELINE_Z) / 2]
        size = [0.0, 0.0, (top_z - BASELINE_Z) / 2]
        pos[long_idx] += long_center
        size[long_idx] = long_half
        size[cross_idx] = cross_half
        spec.worldbody.add_geom(name=f"{name}_{suffix}", size=size, pos=pos, **geom_kwargs)

    # 2. Up-side steps (low end -> peak/valley).
    for i in range(n_steps):
        long_low = -stair_span / 2 + i * step_width
        long_center = long_low + step_width / 2
        top_z = base_top_z + step_sign * (i + 1) * step_height
        _emit_step(f"step_up_{i}", long_center, step_width / 2, top_z)

    # 3. Peak (or valley floor) platform.
    peak_top_z = base_top_z + step_sign * n_steps * step_height
    _emit_step("peak", 0.0, peak_width / 2, peak_top_z)

    # 4. Down-side steps (peak/valley -> high end), mirrored.
    for i in range(n_steps):
        long_low = peak_width / 2 + i * step_width
        long_center = long_low + step_width / 2
        top_z = base_top_z + step_sign * (n_steps - i) * step_height
        _emit_step(f"step_down_{i}", long_center, step_width / 2, top_z)

    return TileEmitResult(base_height=base_height)
