"""`stairs` tile: Colab-style mirrored staircase.

Layout along the chosen axis (default `y`):

    base   up steps      peak       down steps    base
    |____|//|//|//|//|________|\\|\\|\\|\\|____|
              \\               /
               \\_ peak_width _/

All four edges of the tile sit at `base_height` (flat-at-base contract).
Stairs rise from base_height by `n_steps * step_height`, plateau across
`peak_width`, then mirror back down to base_height. v1 only supports the
`mirror` return mode; ramp-back is deferred to v2.

Step geometry: each step is its own box that extends from BASELINE_Z up
to its tread height. The base slab beneath the entire tile provides the
flat margin between the stair span and the tile edges plus the floor under
the steps; step boxes overlap the base inside the stair span (rendering
picks the topmost surface).
"""

from __future__ import annotations

import mujoco as mj

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.30, 0.50, 0.85, 1.0)  # blue

DEFAULT_PARAMS: dict = {
    "step_height": 0.15,
    "step_width": None,  # None => auto-compute to fill the tile's long axis
    "n_steps": 6,
    "axis": "y",
    "peak_width": 0.40,
    "return_mode": "mirror",
    "base_height": 0.0,
    "cross_ratio": 0.90,  # active region covers 90% of cross axis; remainder is flat base margin
    "inverted": False,    # True => steps descend into a pit instead of rising to a peak
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "step_height": (0.08, 0.25),
    # step_width is intentionally NOT randomized — leaving it unset triggers
    # auto-fill so stairs span the full tile regardless of n_steps.
    "n_steps": (3, 12),
    "peak_width": (0.20, 0.50),
    # base_height intentionally not randomized — see flat.py for the rationale.
}


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
    peak_width: float = 0.25,
    return_mode: str = "mirror",
    base_height: float = 0.0,
    cross_ratio: float = 0.90,
    inverted: bool = False,
    output_dir=None,  # unused; accepted for uniform composer API
    terrain_name=None,  # unused; accepted for uniform composer API
) -> TileEmitResult:
    if axis not in ("x", "y"):
        raise ValueError(f"stairs.axis must be 'x' or 'y', got {axis!r}")
    if return_mode != "mirror":
        raise NotImplementedError(
            f"stairs.return_mode={return_mode!r} not in v1; only 'mirror' supported."
        )
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
        raise ValueError(
            f"stairs '{name}': base top z={base_top_z:.3f} <= BASELINE_Z={BASELINE_Z:.3f}; "
            f"increase base_height."
        )

    # Map axis to (long, cross) index pair: 0=x, 1=y.
    long_idx, cross_idx = (1, 0) if axis == "y" else (0, 1)
    long_total = tile_size[long_idx]
    cross_total = tile_size[cross_idx]

    # Auto-fill step_width: when not specified, distribute the remaining
    # long-axis length (after the peak platform) evenly across the up + down
    # ramp segments, so the stairs span the entire tile.
    if step_width is None:
        step_width = (long_total - peak_width) / (2 * n_steps)
        if step_width <= 0:
            raise ValueError(
                f"stairs '{name}': peak_width ({peak_width:.3f} m) >= tile long axis "
                f"({long_total:.3f} m); reduce peak_width or specify step_width explicitly."
            )

    stair_span = 2 * n_steps * step_width + peak_width
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
    cross_half = cross_total * cross_ratio / 2
    if material is not None:
        geom_kwargs["material"] = material
    if rgba is not None:
        geom_kwargs["rgba"] = list(rgba)

    # 1. Base — for upright stairs, a full-tile slab at base_height. For
    #    inverted stairs, only the cross-axis margins are emitted; the
    #    active region (where steps descend) is left open so the pit is
    #    visible from above.
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
            for side, sign in (("a", -1), ("b", +1)):
                pos = [origin_x, origin_y, base_center_z]
                size = [0.0, 0.0, base_half_z]
                pos[cross_idx] += sign * (cross_total / 2 - cross_margin_half)
                size[cross_idx] = cross_margin_half
                size[long_idx] = tile_size[long_idx] / 2
                spec.worldbody.add_geom(
                    name=f"{name}_base_{side}", size=size, pos=pos, **geom_kwargs
                )

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
