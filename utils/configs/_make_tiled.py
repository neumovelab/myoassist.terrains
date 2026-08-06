"""One-shot helper: build a 3x3 tiled JSON from a 3x3 base config.

Replicates the base 3x3 tile pattern into a 9x9 grid; perturbs `seed` on
hfield-backed tiles so each rough patch differs slightly across copies, and
applies a random 0/90/180/270 degree rotation to each block so directional
features (slopes, stairs) no longer all face the same direction.
"""

import json
import random
import sys
from pathlib import Path

base_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
master_seed = int(sys.argv[3]) if len(sys.argv) > 3 else 42

base = json.loads(base_path.read_text(encoding="utf-8"))
br = base["grid"]["rows"]
bc = base["grid"]["cols"]

rng = random.Random(master_seed)

# Pre-pick rotations so the layout is reproducible from master_seed.
# 0/1/2/3 quarter-turns CCW.
block_rotations = [[rng.randint(0, 3) for _ in range(3)] for _ in range(3)]


def rotate_rc(r, c, rows, cols, k):
    """Map (r, c) under k quarter-turns CCW on a rows x cols grid."""
    k = k % 4
    if k == 0:
        return r, c
    if k == 1:  # 90 CCW
        return rows - 1 - c, r
    if k == 2:  # 180
        return rows - 1 - r, cols - 1 - c
    # k == 3, 270 CCW (== 90 CW)
    return c, cols - 1 - r


def rotate_axis(axis, k):
    """Swap x<->y on odd quarter-turns; even rotations leave axis unchanged."""
    if k % 2 == 0 or axis is None:
        return axis
    return "y" if axis == "x" else "x"


tiled_tiles = []
for dr in range(3):
    for dc in range(3):
        k = block_rotations[dr][dc]
        block_idx = dr * 3 + dc
        for t in base["tiles"]:
            new_r, new_c = rotate_rc(t["row"], t["col"], br, bc, k)
            new_params = dict(t.get("params", {}))
            if "axis" in new_params:
                new_params["axis"] = rotate_axis(new_params["axis"], k)
            if "seed" in new_params:
                # Per-copy perturbation so rough patches don't replicate identically.
                new_params["seed"] = int(t["params"]["seed"]) + block_idx * 100
            tiled_tiles.append(
                {
                    "row": new_r + dr * br,
                    "col": new_c + dc * bc,
                    "type": t["type"],
                    "params": new_params,
                }
            )

tiled = {
    "terrain_name": base["terrain_name"] + "_tiled3x3",
    "grid": {
        "rows": br * 3,
        "cols": bc * 3,
        "tile_size": base["grid"]["tile_size"],
    },
    "border": base["border"],
    "palette_preset": base["palette_preset"],
    "tiles": tiled_tiles,
}
# Forward optional top-level fields that don't depend on the grid layout
# (texture binding, palette overrides) so the tiled config behaves identically
# to the base except for the larger footprint.
for optional_key in ("palette", "texture"):
    if optional_key in base:
        tiled[optional_key] = base[optional_key]

out_path.write_text(json.dumps(tiled, indent=2), encoding="utf-8")
rot_summary = " ".join(f"({dr},{dc}):{block_rotations[dr][dc] * 90}deg" for dr in range(3) for dc in range(3))
print(f"Wrote {out_path} with {len(tiled_tiles)} tiles ({tiled['grid']['rows']}x{tiled['grid']['cols']} grid)")
print(f"Block rotations (master_seed={master_seed}): {rot_summary}")
