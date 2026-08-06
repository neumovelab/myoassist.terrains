"""Grow the existing 9x9 tiled terrain by 3 tile-rings -> 15x15.

Keeps the current center 9x9 EXACTLY as-is (tiles copied verbatim from
base_tiled3x3.json, shifted +3 rows/cols), and generates one surrounding
ring of 3x3 base blocks (16 outer blocks). Because the composer auto-centers
the grid, the +3 shift leaves every original tile at its same world position
(15 and 9 are both odd, (15-1)/2 - 3 == (9-1)/2), so the center matches the
current scene exactly and the new terrain extends symmetrically outward.

  3x3 base block grid (9x9)  ->  5x5 base block grid (15x15)
  center 3x3 blocks = preserved current tiles
  outer 16 blocks   = base replicated with per-block rotation + seed offset

Run:
  python utils/configs/_make_tiled_rings.py
Writes utils/configs/base_tiled5x5.json
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "base.json"  # 3x3 motif
CURRENT = HERE / "base_tiled3x3.json"  # existing 9x9 (center, preserved)
OUT = HERE / "base_tiled5x5.json"

N_BLOCKS = 5  # 5x5 base blocks -> 15x15 tiles (one ring added)
CENTER_OFFSET = 1  # center 3x3 blocks start at block index 1
OUTER_SEED_OFFSET = 10000  # keep outer rough seeds clear of the center's
ROTATION_SEED = 142  # rng for the outer-ring block rotations


def rotate_rc(r, c, rows, cols, k):
    k = k % 4
    if k == 0:
        return r, c
    if k == 1:
        return rows - 1 - c, r
    if k == 2:
        return rows - 1 - r, cols - 1 - c
    return c, cols - 1 - r


def rotate_axis(axis, k):
    if k % 2 == 0 or axis is None:
        return axis
    return "y" if axis == "x" else "x"


def main() -> None:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    br, bc = base["grid"]["rows"], base["grid"]["cols"]
    assert (br, bc) == (3, 3), "expects a 3x3 base motif"

    tiles = []

    # 1) Preserve the current 9x9, shifted into the center 3x3 blocks.
    shift = CENTER_OFFSET * br  # +3
    for t in current["tiles"]:
        nt = dict(t)
        nt["row"] = t["row"] + shift
        nt["col"] = t["col"] + shift
        tiles.append(nt)

    # 2) Generate the outer ring of blocks from the base motif.
    rng = random.Random(ROTATION_SEED)
    block_rot = [[rng.randint(0, 3) for _ in range(N_BLOCKS)] for _ in range(N_BLOCKS)]
    for dr in range(N_BLOCKS):
        for dc in range(N_BLOCKS):
            is_center = CENTER_OFFSET <= dr < CENTER_OFFSET + 3 and CENTER_OFFSET <= dc < CENTER_OFFSET + 3
            if is_center:
                continue  # already filled from current
            k = block_rot[dr][dc]
            block_idx = dr * N_BLOCKS + dc
            for t in base["tiles"]:
                nr, nc = rotate_rc(t["row"], t["col"], br, bc, k)
                params = dict(t.get("params", {}))
                if "axis" in params:
                    params["axis"] = rotate_axis(params["axis"], k)
                if "seed" in params:
                    params["seed"] = int(t["params"]["seed"]) + block_idx * 100 + OUTER_SEED_OFFSET
                tiles.append(
                    {
                        "row": nr + dr * br,
                        "col": nc + dc * bc,
                        "type": t["type"],
                        "params": params,
                    }
                )

    out = {
        "terrain_name": "base_tiled5x5",
        "grid": {"rows": br * N_BLOCKS, "cols": bc * N_BLOCKS, "tile_size": base["grid"]["tile_size"]},
        "border": base["border"],
        "palette_preset": base["palette_preset"],
        "tiles": tiles,
    }
    for opt in ("palette", "texture"):
        if opt in base:
            out[opt] = base[opt]

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        f"Wrote {OUT.name}: {len(tiles)} tiles ({out['grid']['rows']}x{out['grid']['cols']}), "
        f"center {len(current['tiles'])} preserved + {len(tiles) - len(current['tiles'])} new"
    )


if __name__ == "__main__":
    main()
