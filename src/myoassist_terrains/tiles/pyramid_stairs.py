"""`pyramid_stairs` tile: square pyramid built from concentric box rings.

Layout: a base slab covering the full tile at `base_height`, with N nested
box "levels" stacked on top. Each level is a centered box whose footprint
shrinks by `step_width` on each side relative to the level below, with its
top face `step_height` above the previous level's top.

All four edges of the tile sit at `base_height` (the base slab provides the
boundary contract); the pyramid rises from inside the tile.

Walkability: every level forms a square ring around the next, so a model
can walk up one side and back down any other.

Both forms are supported: the default rising pyramid, and, with
`inverted=True`, a stepped pit that descends into the base slab (its floor
is checked to stay above `BASELINE_Z`).
"""

from __future__ import annotations

import mujoco as mj

from myoassist_terrains.tiles.base import BASELINE_Z, TileEmitResult


# Diverse-mode default; placeholder until a curated palette is provided.
DEFAULT_RGBA: tuple[float, float, float, float] = (0.85, 0.70, 0.25, 1.0)  # yellow / ochre

DEFAULT_PARAMS: dict = {
    "step_height": 0.20,
    "step_width": 0.50,  # how much each level shrinks per side
    "n_steps": 5,
    "outer_margin": 0.5,  # flat margin around the pyramid's base level
    "inverted": False,
    "base_height": 0.0,
}

PARAM_RANGES: dict[str, tuple[float, float]] = {
    "step_height": (0.10, 0.30),
    "step_width": (0.30, 0.80),
    "n_steps": (3, 8),
    "outer_margin": (0.2, 1.0),
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
    step_height: float = 0.20,
    step_width: float = 0.50,
    n_steps: int = 5,
    outer_margin: float = 0.5,
    inverted: bool = False,
    base_height: float = 0.0,
    output_dir=None,  # unused
    terrain_name=None,  # unused
) -> TileEmitResult:
    if step_height <= 0 or step_width <= 0 or outer_margin < 0:
        raise ValueError("step_height and step_width must be positive; outer_margin >= 0")
    if n_steps < 1:
        raise ValueError(f"pyramid_stairs.n_steps must be >= 1 (got {n_steps})")

    base_top_z = origin_xyz[2] + base_height
    if base_top_z <= BASELINE_Z:
        raise ValueError(
            f"pyramid_stairs '{name}': base top z={base_top_z:.3f} <= "
            f"BASELINE_Z={BASELINE_Z:.3f}; increase base_height."
        )

    # If the pyramid would collapse before reaching n_steps, the per-level
    # loop below breaks early — emit fewer levels rather than erroring out.
    # This makes randomized configs robust to occasional unfortunate
    # parameter combinations (steep step_width × high n_steps).

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
    sign_z = -1.0 if inverted else +1.0

    # Sanity-check that an inverted pit floor stays above BASELINE_Z.
    deepest_top = base_top_z + sign_z * n_steps * step_height
    if inverted and deepest_top <= BASELINE_Z:
        raise ValueError(
            f"pyramid_stairs '{name}' inverted: pit floor z={deepest_top:.3f} would "
            f"land at or below BASELINE_Z={BASELINE_Z:.3f}. Reduce n_steps × "
            f"step_height or raise base_height."
        )

    outer_half_w = tile_size[0] / 2 - outer_margin
    outer_half_l = tile_size[1] / 2 - outer_margin

    if not inverted:
        # 1a. Upright: full-tile base slab at base_height.
        spec.worldbody.add_geom(
            name=f"{name}_base",
            size=[tile_size[0] / 2, tile_size[1] / 2, base_half_z],
            pos=[origin_x, origin_y, base_center_z],
            **geom_kwargs,
        )
    else:
        # 1b. Inverted: emit the base as a 4-sided FRAME around the active
        #     pyramid footprint (outer_margin strip on each side). Inside the
        #     frame is open so the descending pit is visible from above.
        # Top wall (large +y).
        spec.worldbody.add_geom(
            name=f"{name}_frame_n",
            size=[tile_size[0] / 2, outer_margin / 2, base_half_z],
            pos=[origin_x, origin_y + tile_size[1] / 2 - outer_margin / 2, base_center_z],
            **geom_kwargs,
        )
        # Bottom wall (large -y).
        spec.worldbody.add_geom(
            name=f"{name}_frame_s",
            size=[tile_size[0] / 2, outer_margin / 2, base_half_z],
            pos=[origin_x, origin_y - tile_size[1] / 2 + outer_margin / 2, base_center_z],
            **geom_kwargs,
        )
        # East wall (large +x), only spanning the inner length to avoid
        # double-coverage with the n/s walls at the corners.
        spec.worldbody.add_geom(
            name=f"{name}_frame_e",
            size=[outer_margin / 2, outer_half_l, base_half_z],
            pos=[origin_x + tile_size[0] / 2 - outer_margin / 2, origin_y, base_center_z],
            **geom_kwargs,
        )
        # West wall.
        spec.worldbody.add_geom(
            name=f"{name}_frame_w",
            size=[outer_margin / 2, outer_half_l, base_half_z],
            pos=[origin_x - tile_size[0] / 2 + outer_margin / 2, origin_y, base_center_z],
            **geom_kwargs,
        )

    # 2. Pyramid levels. Level i (1..n_steps) is a centered box; for upright
    # pyramids each level shrinks AND rises (smallest at top), and the larger
    # boxes naturally sit underneath. For inverted pits we want the OPPOSITE:
    # the LARGEST footprint is at the deepest single level (covers the
    # bottom of the pit), and the smaller boxes sit closer to the surface,
    # exposing concentric "rings" from above.
    if not inverted:
        for i in range(1, n_steps + 1):
            level_half_w = outer_half_w - (i - 1) * step_width
            level_half_l = outer_half_l - (i - 1) * step_width
            if level_half_w <= 0 or level_half_l <= 0:
                break
            top_z = base_top_z + i * step_height
            half_z = (top_z - BASELINE_Z) / 2
            center_z = (top_z + BASELINE_Z) / 2
            spec.worldbody.add_geom(
                name=f"{name}_level_{i}",
                size=[level_half_w, level_half_l, half_z],
                pos=[origin_x, origin_y, center_z],
                **geom_kwargs,
            )
    else:
        # Inverted: levels 1..n_steps-1 are emitted as 4-wall FRAMES (square
        # rings) so the central area is open; the deepest level (n_steps) is
        # a solid pit floor. From above you see concentric square rings
        # descending into the pit.
        for i in range(1, n_steps):  # frames
            outer_w_i = outer_half_w - (i - 1) * step_width
            outer_l_i = outer_half_l - (i - 1) * step_width
            inner_w_i = outer_half_w - i * step_width
            inner_l_i = outer_half_l - i * step_width
            if inner_w_i <= 0 or inner_l_i <= 0:
                break
            top_z_i = base_top_z - i * step_height
            half_z_i = (top_z_i - BASELINE_Z) / 2
            if half_z_i <= 0:
                break
            center_z_i = (top_z_i + BASELINE_Z) / 2

            # Wall thickness in each axis
            wall_y = (outer_l_i - inner_l_i) / 2  # half-extent of N/S walls along y
            wall_x = (outer_w_i - inner_w_i) / 2  # half-extent of E/W walls along x

            # North wall (full outer width along x, wall_y along y).
            spec.worldbody.add_geom(
                name=f"{name}_ring_{i}_n",
                size=[outer_w_i, wall_y, half_z_i],
                pos=[origin_x, origin_y + (inner_l_i + outer_l_i) / 2, center_z_i],
                **geom_kwargs,
            )
            spec.worldbody.add_geom(
                name=f"{name}_ring_{i}_s",
                size=[outer_w_i, wall_y, half_z_i],
                pos=[origin_x, origin_y - (inner_l_i + outer_l_i) / 2, center_z_i],
                **geom_kwargs,
            )
            # East/West walls inset along y so they don't double-cover the corners.
            spec.worldbody.add_geom(
                name=f"{name}_ring_{i}_e",
                size=[wall_x, inner_l_i, half_z_i],
                pos=[origin_x + (inner_w_i + outer_w_i) / 2, origin_y, center_z_i],
                **geom_kwargs,
            )
            spec.worldbody.add_geom(
                name=f"{name}_ring_{i}_w",
                size=[wall_x, inner_l_i, half_z_i],
                pos=[origin_x - (inner_w_i + outer_w_i) / 2, origin_y, center_z_i],
                **geom_kwargs,
            )

        # Pit floor (solid box) at the deepest level.
        floor_half_w = outer_half_w - (n_steps - 1) * step_width
        floor_half_l = outer_half_l - (n_steps - 1) * step_width
        if floor_half_w > 0 and floor_half_l > 0:
            floor_top_z = base_top_z - n_steps * step_height
            floor_half_z = (floor_top_z - BASELINE_Z) / 2
            if floor_half_z > 0:
                floor_center_z = (floor_top_z + BASELINE_Z) / 2
                spec.worldbody.add_geom(
                    name=f"{name}_pit_floor",
                    size=[floor_half_w, floor_half_l, floor_half_z],
                    pos=[origin_x, origin_y, floor_center_z],
                    **geom_kwargs,
                )

    return TileEmitResult(base_height=base_height)
