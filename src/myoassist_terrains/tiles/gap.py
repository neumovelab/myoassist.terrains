"""`gap` tile: a flat tile bisected by an empty trench.

Two flat half-slabs are emitted on either side of the gap; the gap region
itself contains no geometry. A model that doesn't clear the gap falls
through to the invisible `terrain` backstop floor.

Per the plan, `gap_width` defaults to a range supporting both step-able and
fail-able cases — it's intentional that wide gaps can defeat the policy,
since this terrain type exists to surface that failure mode.

`axis` controls which way the trench RUNS along: `axis="y"` makes the
trench long along y (bisecting in the x direction), and vice versa for
`axis="x"`.

v1: no walls — the gap is simply absence of geometry. (If it ever reads
visually unclear, we can add side walls in v2.)
"""

from __future__ import annotations

import mujoco as mj

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.30, 0.30, 0.30, 1.0)  # dark slate

DEFAULT_PARAMS: dict = {
    "gap_width": 0.5,
    "axis": "y",
    "base_height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "gap_width": (0.1, 1.0),
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
    gap_width: float = 0.5,
    axis: str = "y",
    base_height: float = 0.0,
    output_dir=None,
    terrain_name=None,
) -> TileEmitResult:
    if axis not in ("x", "y"):
        raise ValueError(f"gap.axis must be 'x' or 'y' (got {axis!r})")
    if gap_width <= 0:
        raise ValueError(f"gap.gap_width must be > 0 (got {gap_width})")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"gap '{name}': base top z={base_top_z:.3f} <= "
            f"BASELINE_Z={BASELINE_Z:.3f}; increase base_height."
        )

    # The trench RUNS along `axis`; it bisects the perpendicular axis.
    # axis='y' => trench long in y, gap separates x.
    # axis='x' => trench long in x, gap separates y.
    if axis == "y":
        bisect_idx = 0  # gap separates along x
        run_idx = 1  # trench length along y
    else:
        bisect_idx = 1
        run_idx = 0

    bisect_total = tile_size[bisect_idx]
    run_total = tile_size[run_idx]

    if gap_width >= bisect_total:
        raise ValueError(
            f"gap '{name}': gap_width ({gap_width:.3f}) >= tile size along "
            f"perpendicular axis ({bisect_total:.3f}); the gap would consume the whole tile."
        )

    origin_x, origin_y = origin_xyz[0], origin_xyz[1]

    geom_kwargs: dict = {
        "type": mj.mjtGeom.mjGEOM_BOX,
        "contype": 1,
        "conaffinity": 1,
    }
    if material is not None:
        geom_kwargs["material"] = material
    if rgba is not None:
        geom_kwargs["rgba"] = list(rgba)

    base_half_z = (base_top_z - BASELINE_Z) / 2
    base_center_z = (base_top_z + BASELINE_Z) / 2

    # Each half-slab covers from the tile edge to the gap edge along the
    # bisect axis, full tile along the run axis.
    half_slab_half_extent = (bisect_total - gap_width) / 4  # half the slab's extent along bisect
    slab_offset = (bisect_total + gap_width) / 4  # distance from tile center to slab center

    for side, sign in (("a", -1), ("b", +1)):
        size = [0.0, 0.0, base_half_z]
        size[bisect_idx] = half_slab_half_extent
        size[run_idx] = run_total / 2
        pos = [origin_x, origin_y, base_center_z]
        pos[bisect_idx] += sign * slab_offset
        spec.worldbody.add_geom(
            name=f"{name}_slab_{side}",
            size=size,
            pos=pos,
            **geom_kwargs,
        )

    return TileEmitResult(base_height=base_height)
