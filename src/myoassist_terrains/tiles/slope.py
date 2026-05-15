"""`slope` tile: mirrored ramp ("up + plateau + down") along one axis.

Geometry along the chosen axis (default `y`):

    base   up ramp        plateau        down ramp   base
    |____|////////|//=================//|\\\\\\\\|____|
                  \\         peak        /
                   \\__ plateau_long ___/

All four edges of the tile sit at `base_height` along the slope axis (low
ends of each ramp). The cross-axis edges show the slope profile (ramp →
plateau → ramp), which means connectors on those sides will see a vertical
side wall against the connector at the lower neighbor height — visually
similar to a ridge with side walls. This matches the stairs tile's behavior
on its cross axis and is the v1 boundary-contract compromise.

Plateau width is computed dynamically: `plateau_ratio * tile_long`. Peak
height = (tile_long - plateau) / 2 * tan(angle), so it scales naturally with
both tile size and steepness.

`direction` is reserved for v2 turn modes (`turn_left`, `turn_right`,
`random`); v1 only supports `mirror`.
"""

from __future__ import annotations

import math

import mujoco as mj

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.40, 0.65, 0.40, 1.0)  # sage green

DEFAULT_PARAMS: dict = {
    "angle_deg": 12.0,
    "axis": "y",
    "direction": "mirror",
    "plateau_ratio": 0.10,
    "base_height": 0.0,
    "cross_ratio": 0.90,  # active region covers 90% of cross axis; remainder is flat base margin
    "inverted": False,    # True => ramps descend into a valley instead of rising to a peak
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "angle_deg": (5.0, 25.0),
    "plateau_ratio": (0.05, 0.30),
    # base_height intentionally not randomized — see flat.py for the rationale.
}

_RAMP_THICKNESS = 0.1


def emit(
    spec: mj.MjSpec,
    origin_xyz: tuple[float, float, float],
    name: str,
    *,
    tile_size: tuple[float, float],
    rgba: tuple[float, float, float, float] | None = None,
    material: str | None = None,
    angle_deg: float = 12.0,
    axis: str = "y",
    direction: str = "mirror",
    plateau_ratio: float = 0.10,
    base_height: float = 0.0,
    cross_ratio: float = 0.90,
    inverted: bool = False,
    output_dir=None,  # unused; accepted for uniform composer API
    terrain_name=None,  # unused; accepted for uniform composer API
) -> TileEmitResult:
    if axis not in ("x", "y"):
        raise ValueError(f"slope.axis must be 'x' or 'y', got {axis!r}")
    if direction != "mirror":
        raise NotImplementedError(
            f"slope.direction={direction!r} not supported in v1; only 'mirror'. "
            f"Turn modes ('turn_left', 'turn_right') and 'random' are planned for v2."
        )
    if not (0.0 < angle_deg < 90.0):
        raise ValueError(f"slope.angle_deg must satisfy 0 < angle < 90 (got {angle_deg})")
    if not (0.0 < plateau_ratio < 1.0):
        raise ValueError(
            f"slope.plateau_ratio must satisfy 0 < ratio < 1 (got {plateau_ratio})"
        )
    if not (0.0 < cross_ratio <= 1.0):
        raise ValueError(f"slope.cross_ratio must satisfy 0 < ratio <= 1, got {cross_ratio}")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"slope '{name}': base top z={base_top_z:.3f} <= BASELINE_Z={BASELINE_Z:.3f}; "
            f"increase base_height."
        )

    long_idx, cross_idx = (1, 0) if axis == "y" else (0, 1)
    long_total = tile_size[long_idx]
    cross_total = tile_size[cross_idx]

    angle_rad = math.radians(angle_deg)

    plateau_long = plateau_ratio * long_total
    ramp_long = (long_total - plateau_long) / 2  # length of each ramp side along long axis

    if ramp_long <= 0.0:
        raise ValueError(
            f"slope '{name}': computed ramp length non-positive (plateau_ratio={plateau_ratio} "
            f"too large for tile_long={long_total})"
        )

    # Sign of the vertical excursion: +1 = rise to a peak, -1 = descend to a valley.
    sign_z = -1.0 if inverted else +1.0
    peak_above_base = ramp_long * math.tan(angle_rad)
    peak_top_z = base_top_z + sign_z * peak_above_base
    if peak_top_z <= BASELINE_Z:
        raise ValueError(
            f"slope '{name}' inverted: valley floor z={peak_top_z:.3f} would land at or "
            f"below BASELINE_Z={BASELINE_Z:.3f}. Reduce angle_deg or raise base_height."
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

    # 1. Base — full tile slab when upright; cross-margin strips only when
    #    inverted so the active region remains open to the descent.
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

    # 2. Plateau slab — thin slab matching the ramp slab thickness, bridging
    #    the ramp tops at peak height. Its top face is at peak_top_z; below
    #    it is empty space down to the base slab.
    plateau_size = [0.0, 0.0, _RAMP_THICKNESS / 2]
    plateau_size[long_idx] = plateau_long / 2
    plateau_size[cross_idx] = cross_half
    plateau_pos = [origin_x, origin_y, peak_top_z - _RAMP_THICKNESS / 2]
    spec.worldbody.add_geom(
        name=f"{name}_plateau",
        size=plateau_size,
        pos=plateau_pos,
        **geom_kwargs,
    )

    # 3. Ramps. Each ramp covers `ramp_long` along the long axis. Box length
    #    along its own primary axis (untilted) is ramp_long / cos(angle); after
    #    rotation by `angle_rad` about the cross axis, it projects to ramp_long
    #    in tile frame and rises by ramp_long * tan(angle) = peak_above_base.
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    box_long_half = (ramp_long / cos_a) / 2
    ramp_size = [0.0, 0.0, _RAMP_THICKNESS / 2]
    ramp_size[long_idx] = box_long_half
    ramp_size[cross_idx] = cross_half

    # Slab-thickness compensation: when a thin slab of thickness t is tilted
    # by angle a about the cross axis, its top-face midpoint sits offset from
    # the body center by (-t/2 * sin a, +t/2 * cos a) along (long, z) for the
    # up ramp, and (+t/2 * sin a, +t/2 * cos a) for the down ramp. To make
    # the top-face midpoint land at the math midpoint of the ramp surface
    # (low_edge .. plateau_edge), shift the body by the negative of those
    # offsets. After this correction, the ramp's top surface meets the
    # plateau's top exactly at peak_top_z.
    # The thickness compensation for the long-axis is direction-dependent:
    # for inverted (downward) ramps the top-face midpoint offset flips sign.
    long_shift = _RAMP_THICKNESS / 2 * sin_a * sign_z
    z_shift = -_RAMP_THICKNESS / 2 * cos_a
    ramp_center_z = (base_top_z + peak_top_z) / 2 + z_shift

    # Rotation axis & sign so the up ramp's +long_local end is the inner side
    # (plateau or valley floor): for axis='y' rotate about +x by +angle to
    # lift +y, then negate for inverted to drop +y instead.
    if axis == "y":
        rot_axis_xyz_idx = 0  # rotate about +x
        rot_angle_up = +angle_rad * sign_z
    else:
        rot_axis_xyz_idx = 1  # rotate about +y
        rot_angle_up = -angle_rad * sign_z

    half_up = rot_angle_up / 2
    quat_up = [math.cos(half_up), 0.0, 0.0, 0.0]
    quat_up[rot_axis_xyz_idx + 1] = math.sin(half_up)

    # Up ramp: low side. Box centered on long axis at the midpoint between
    # the tile's low edge and the plateau's near edge, plus the thickness
    # shift so the top surface meets peak_top_z at the plateau edge.
    up_long_center = -(long_total + plateau_long) / 4
    up_pos = [origin_x, origin_y, ramp_center_z]
    up_pos[long_idx] += up_long_center + long_shift

    spec.worldbody.add_geom(
        name=f"{name}_ramp_up",
        size=ramp_size,
        pos=up_pos,
        quat=quat_up,
        **geom_kwargs,
    )

    # Down ramp: high side, mirrored. Same vertical center, opposite tilt,
    # opposite long shift.
    rot_angle_down = -rot_angle_up
    half_down = rot_angle_down / 2
    quat_down = [math.cos(half_down), 0.0, 0.0, 0.0]
    quat_down[rot_axis_xyz_idx + 1] = math.sin(half_down)

    down_long_center = +(long_total + plateau_long) / 4
    down_pos = [origin_x, origin_y, ramp_center_z]
    down_pos[long_idx] += down_long_center - long_shift

    spec.worldbody.add_geom(
        name=f"{name}_ramp_down",
        size=ramp_size,
        pos=down_pos,
        quat=quat_down,
        **geom_kwargs,
    )

    return TileEmitResult(base_height=base_height)
