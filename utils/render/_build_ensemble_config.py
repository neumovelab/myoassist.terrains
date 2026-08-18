"""Generate the ensemble render config(s) from the per-variant pose lists.

Each variant model has a fixed nq dictated by its joint set. Hand-pasting
qpos strings is error-prone (one missing token shifts every joint), so this
script splits the strings, length-checks against the compiled model, and
writes a clean JSON the renderer can consume.

Emits two configs:
  myoassist_ensemble_config.json        — small 3x3 base, raw poses (21 inst)
  myoassist_ensemble_tiled_config.json  — 9x9 tiled, each pose transposed onto
                                       all 9 blocks with rotation matching
                                       the terrain (master_seed=42).

Re-run after editing poses or cameras to refresh both outputs.
"""

import json
import math
from pathlib import Path

import mujoco

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "myoassist_ensemble_config.json"
TILED_OUT_PATH = HERE / "myoassist_ensemble_tiled_config.json"

# Block rotations applied by utils/configs/_make_tiled.py
# with master_seed=42. Indices are [dr][dc] (matching the script's loop
# order); each value is k = number of quarter-turns in the rotate_rc()
# convention. If you rebuild the tiled terrain with a different seed,
# update this table to match the new block_rotations printout.
BLOCK_ROTATIONS = [
    [0, 0, 2],
    [1, 1, 1],
    [0, 0, 3],
]
# Block spacing in qpos units. 3 tiles * 8m tile_size + 2 borders * 0.8m
# = 25.6m main extent; centre-to-centre between adjacent blocks accounts
# for the connector row, giving 26.4m. Matches the previous tiled config.
BLOCK_SPACING = 26.4


def parse(qpos_str: str) -> list[float]:
    """Tokenise a whitespace-separated qpos string into a flat float list."""
    return [float(tok) for tok in qpos_str.replace("\n", " ").split()]


def rotate_qpos_xz(px: float, pz: float, k: int) -> tuple[float, float]:
    """Rotate horizontal qpos coords to match a tile-grid rotation by k.

    The terrain's rotate_rc(k) acts on (row, col) such that the equivalent
    world (X, Y) transform is:
        k=1: (X, Y) -> ( Y, -X)   (90 deg CW from above)
        k=2: (X, Y) -> (-X, -Y)   (180 deg)
        k=3: (X, Y) -> (-Y,  X)   (90 deg CCW from above)
    qpos[0] = X_world but qpos[2] = -Y_world (pelvis_tz axis lands on
    world -Y after the pelvis-body's 90 deg X-quat). Re-deriving in qpos
    space:
        k=1: (px, pz) -> (-pz,  px)
        k=2: (px, pz) -> (-px, -pz)
        k=3: (px, pz) -> ( pz, -px)
    """
    k %= 4
    if k == 0:
        return px, pz
    if k == 1:
        return -pz, px
    if k == 2:
        return -px, -pz
    return pz, -px  # k == 3


def yaw_tilt_list(tilt: float, lst: float, alpha: float) -> tuple[float, float]:
    """Rotate (tilt, list) by yaw angle `alpha` around world +Z.

    Joint chain order on the pelvis body is tilt -> list -> rotation
    (parent-to-body), so the tilt axis is essentially world-fixed (world -Y
    at rest) and adding to pelvis_rotation alone does NOT spin the lean
    direction with the rest of the body. Treating (tilt, list) as a small
    2D lean vector in world horizontal (head's projected XY direction is
    (-tilt, -list) at zero rotation), a world-+Z yaw by alpha rotates that
    vector by alpha. Decomposing back to joint values yields the formula
    below. Accurate for moderate tilt/list (<~30 deg); for very large
    leans a full quaternion decomposition would be more correct.
    """
    ca = math.cos(alpha)
    sa = math.sin(alpha)
    new_tilt = tilt * ca - lst * sa
    new_list = tilt * sa + lst * ca
    return new_tilt, new_list


def transpose_to_blocks(qpos: list[float]) -> list[list[float]]:
    """Return 9 transposed copies of `qpos`, one per block in the tiled grid.

    Rotates the horizontal position (qpos[0], qpos[2]) about the small-base
    centre by the block's k and translates to the block centre. The block
    rotation k is a CW quarter-turn around world +Z in tile-grid space, so
    the body is yawed by alpha = -k * pi/2: that yaw is split between
    pelvis_rotation (qpos[5]) and the (pelvis_tilt, pelvis_list) pair so
    BOTH the facing direction and the lean direction follow the tile.
    The rest of qpos (height, leg joints, etc.) is untouched.
    """
    out: list[list[float]] = []
    for dr in range(3):
        for dc in range(3):
            k = BLOCK_ROTATIONS[dr][dc]
            bx = (dc - 1) * BLOCK_SPACING
            # qpos[2] coord of block centre: dr=0 -> +spacing (since
            # qpos[2] = -world_Y and dr=0 is at -world_Y).
            bz = (1 - dr) * BLOCK_SPACING
            rx, rz = rotate_qpos_xz(qpos[0], qpos[2], k)
            alpha = -k * (math.pi / 2.0)  # CW yaw to match tile rotation
            new_tilt, new_list = yaw_tilt_list(qpos[3], qpos[4], alpha)
            new_qpos = list(qpos)
            new_qpos[0] = bx + rx
            new_qpos[2] = bz + rz
            new_qpos[3] = new_tilt
            new_qpos[4] = new_list
            new_qpos[5] = qpos[5] + alpha
            out.append(new_qpos)
    return out


# Each entry: (alias, model_xml, [pose_str, pose_str, ...]).
# Poses are pasted verbatim from the user-supplied list. Order within
# qpos is the joint order MuJoCo reports after compiling each model XML.
POSE_SETS = [
    (
        "osl_ka",
        "26muscle_3D/myoLeg26_3D_OSL_KA.xml",
        [
            # Pose 1
            "2.176 1.025 4.992 0.031416 -0.188496 1.66505 0.746525 -0.069725 -0.09772 0.65961 -0.005236 -0.200225 0.00711 0 0.00411 -0.395 -0.96178 0.33417 0.403172 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0 0.12 0 -0.24 0.41 0 0 0 0.11 0 -0.24 0.61 0 0 0 0 0 0 0 0 0",
            # Pose 2
            "-8.832 0.88 -9.088 -0.262 0.15708 -0.47124 0.59775 0 0 0.24081 -0.0737 -0.174 0 0 0.00411 -0.395 -0.436 0 0 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0 0.12 0 -0.285 0.5 0 0 0 0.11 0 0.0075 0.47 0 0 0 0 0 0 0 0 0",
            # Pose 3
            "-2.432 0.4 -11.008 0.251328 0.031416 -3.1416 1.1117 0 0 0.92136 -0.0737 0.205525 0 0 0.00411 -0.395 -0.436 0.349 0.5236 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0 0.12 0 0.12 0.41 0 0 0 0.11 0 0.2325 0.45 0 0 0 0 0 0 0 0 0",
        ],
    ),
    (
        "osl_a",
        "26muscle_3D/myoLeg26_OSL_A.xml",
        [
            "-6.144 1.45 6.784 -0.251328 0.094248 -0.47124 0.503075 0 0 0.00411 -0.395 -0.366995 -0.0737 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 -0.0785 0 0 0.00411 -0.395 -1.32878 0.297095 0 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.33 0.54 0 0 0 0.11 0 -0.24 0.43 0 0 0 0 0 0 0 0 0",
            "9.6 0.876 -7.936 0.094248 0.094248 -2.45045 0.503075 0 0 0.00411 -0.395 -0.366995 -0.0737 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 -0.0785 0 0 0.00411 -0.395 -0.73399 0.297095 0 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.33 0.54 0 0 0 0.11 0 -0.24 0.43 0 0 0 0 0 0 0 0 0",
            "-10.752 1.6 6.4 -0.47124 -0.094248 0.251328 1.55802 0 0 0.00411 -0.395 -1.56922 0.5236 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.692425 0 0 0.00411 -0.395 -0.847885 0.133965 0.5236 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.4425 1.01 0 0 0 0.11 0 -0.24 0.77 0 0 0 0 0 0 0 0 0",
        ],
    ),
    (
        "humotech",
        "26muscle_3D/myoLeg26_HUMOTECH.xml",
        [
            "-8.704 0.95 -0.768 -0.31416 -0.251328 0.47124 1.01702 0 0 0.00411 -0.395 -0.73399 -0.0737 0.5 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.16495 0 0 0.00411 -0.395 -1.44267 0.349 0.3005 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.28 0 -0.5325 0.67 0 0 0 0.16 0 -0.195 0.52 0 0 0 0 0 0 0 0 0",
            "10.752 1.5 7.04 0.251328 -0.031416 3.1416 1.19285 0 0 0.00411 -0.395 -1.02506 0.06723 0.3455 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.043225 0 0 0.00411 -0.395 -0.341685 -0.05141 0.3725 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.3975 0.5 0 0 0 0.11 0 -0.285 0.65 0 0 0 0 0 0 0 0 0",
            "-10.752 0.85 -11.648 0.251328 0.031416 3.1416 1.53097 0 0 0.00411 -0.395 -1.27816 -0.06624 0.3155 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.192 0 0 0.00411 -0.395 -0.436 0.349 0.473 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.33 0.4 0 0 0 0.11 0 0 0.86 0 0 0 0 0 0 0 0 0",
            # Pose 4
            "6.528 0.95 -8.448 -0.094248 0 0.879648 -0.174 0 0 0.00411 -0.395 -0.366995 0.178455 0.4385 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.436 0 0 0.00411 -0.395 0 -0.08107 0.359 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 0 0.56 0 0 0 0.11 0 0.3675 0.43 0 0 0 0 0 0 0 0 0",
        ],
    ),
    (
        "dephy",
        "26muscle_3D/myoLeg26_DEPHY.xml",
        [
            "-8.192 0.975 1.024 0.094248 0.031416 -2.85886 0.436 0 0 0.00411 -0.395 -0.0873 -0.0737 0 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 -0.174 0 0 0.00411 -0.395 -0.436 0 0 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.24 0.34 0 0 0 0.11 0 -0.0825 0.41 0 0 0 0 0 0 0 0 0",
            "10.75 0.975 -10.95 -0.31416 0.251328 -0.47124 0.698 0 0 0.00411 -0.395 -1.55656 0.349 0.2 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 1.1658 0 0 0.00411 -0.395 -0.5062 -0.21454 0.110982 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 0.2325 0.38 0 0 0 0.11 0 0.21 0.56 0 0 0 0 0 0 0 0 0",
            "6.784 0.5 -2.944 0.031416 -0.188496 1.85354 1.28752 0 0 0.00411 -0.395 -1.07568 0.2007 0.2 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.192 0 0 0.00411 -0.395 -0.436 0.349 0.473 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.33 0.4 0 0 0 0.11 0 0 0.86 0 0 0 0 0 0 0 0 0",
            # Pose 4
            "-1.024 1.4 11.136 0.031416 0.15708 -1.79071 -0.05145 0 0 0.00411 -0.395 -1.32878 0.33417 0 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.746525 0 0 0.00411 -0.395 -0.366995 -0.02175 0.2 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 0.165 0.5 0 0 0 0.11 0 0.075 0.43 0 0 0 0 0 0 0 0 0",
        ],
    ),
    (
        "hmedi",
        "26muscle_3D/myoLeg26_HMEDI.xml",
        [
            "-1.536 0.88 1.28 0.094248 0.094248 -2.23054 0.436 0 0 0.00411 -0.395 -0.0873 -0.0737 0 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 -0.174 0 0 0.00411 -0.395 -0.436 0 0 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.3975 0.49 0 0 0 0.11 0 -0.0825 0.77 0 0 0 0 0 0 0 0 0",
            "2.944 0.5 -5.888 0.094248 -0.15708 2.51328 0.81415 0 0 0.00411 -0.395 -0.771955 0.015325 0.15708 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 -0.173175 0 0 0.00411 -0.395 -0.96178 0.349 0.5236 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.1725 0.16 0 0 0 0.11 0 0.12 0.74 0 0 0 0 0 0 0 0 0",
            "9.088 1.2 11.392 -0.031416 0.251328 -1.31947 0.81415 0 0 0.00411 -0.395 -0.341685 0.015325 0.15708 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.232575 0 0 0.00411 -0.395 -1.41736 0.349 0.5236 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.195 0.23 0 0 0 0.11 0 -0.33 0.29 0 0 0 0 0 0 0 0 0",
            # Pose 4
            "-6.784 0.88 -9.088 0.094248 0.15708 -2.41903 -0.174 0 0 0.00411 -0.395 -0.436 0 0 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.436 0 0 0.00411 -0.395 -0.0873 -0.0737 0 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 0 0.54 0 0 0 0.11 0 0.2775 0.36 0 0 0 0 0 0 0 0 0",
        ],
    ),
    (
        "openexo",
        "26muscle_3D/myoLeg26_OPENEXO.xml",
        [
            "9.984 0.36 2.432 -0.094248 -0.094248 1.09956 0.6248 0 0 0.00411 -0.395 -0.392305 -0.49631 0.15708 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.232575 0 0 0.00411 -0.395 -1.41736 0.349 0.5236 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.195 0.23 0 0 0 0.11 0 -0.1275 0.7 0 0 0 0 0 0 0 0 0",
            "-11.648 0.85 -1.792 0.031416 0.094248 -1.66505 -0.349 0 0 0.00411 -0.395 -0.620095 0.18587 0.219912 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 0.436 0 0 0.00411 -0.396801 -0.392305 0.0524 0.251328 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 0.12 0.4 0 0 0 0.11 0 0.2775 0.56 0 0 0 0 0 0 0 0 0",
            "-0.64 0.89 3.84 -0.031416 0 -0.879648 0.557175 0 0 0.00411 -0.395 -0.5062 -0.19971 0 -0.033 -0.038 0.055 0.022 0.049 0.026 -0.027 -0.4 -0.025 -0.174 0 0 0.00411 -0.395 -0.544165 0.349 0.335104 -0.033 -0.038 0.055 0.022 0.048 0.026 -0.027 -0.4 0.025 0.12 0 -0.1725 0.4 0 0 0 0.11 0 0 0.54 0 0 0 0 0 0 0 0 0",
        ],
    ),
]


# Cameras: keep camera 1 from the tiled config; add the three new framings
# the user provided. Renderer numbers output as _c1.._c4.
CAMERAS = [
    # 1. Kept from previous tiled-scene config
    {"pos": [14.474, 15.784, 7.140], "xyaxes": [-0.701, 0.713, 0.000, -0.242, -0.238, 0.941]},
    # 2. High wide
    {"pos": [14.787, 28.325, 10.728], "xyaxes": [-0.857, 0.515, 0.000, -0.142, -0.236, 0.961]},
    # 3. Close low
    {"pos": [4.877, 12.458, 2.376], "xyaxes": [-0.866, 0.500, 0.000, -0.055, -0.096, 0.994]},
    # 4. Side angle
    {"pos": [17.599, -7.646, 4.024], "xyaxes": [0.432, 0.902, 0.000, -0.182, 0.087, 0.979]},
    # 5. Reverse oblique
    {"pos": [-20.023, -6.732, 5.604], "xyaxes": [0.320, -0.948, 0.000, 0.310, 0.104, 0.945]},
]


def main() -> None:
    models = []
    for alias, model_rel, poses in POSE_SETS:
        model_path = HERE / model_rel
        if not model_path.exists():
            print(f"FAIL  {alias}: model not found at {model_path}")
            return
        m = mujoco.MjModel.from_xml_path(str(model_path))
        nq = m.nq

        instances = []
        for i, pose_str in enumerate(poses, start=1):
            qpos = parse(pose_str)
            if len(qpos) != nq:
                print(f"FAIL  {alias} pose {i}: got {len(qpos)} values, model expects nq={nq}. Check for missing tokens.")
                return
            instances.append({"qpos": qpos})
        models.append(
            {
                "name": alias,
                "model": model_rel.replace("\\", "/"),
                "instances": instances,
            }
        )
        print(f"OK    {alias:10s} {len(instances)} poses, nq={nq}")

    config = {
        "_comment": (
            "First-pass ensemble for the small myoassist_base terrain. "
            "Camera 0 is the legacy tiled-scene camera; cameras 1-3 are "
            "the user-provided framings. Re-run _build_ensemble_config.py "
            "after editing poses to regenerate. 'terrain_build' builds the "
            "real styled terrain from the JSON config (the static "
            "terrain_config.xml only holds a flat placeholder floor); "
            "'velocity_map' overlays the per-tile flow arrows from the SAME "
            "config so terrain and arrows always match."
        ),
        "terrain_build": {
            "config": "../configs/myoassist_base.json",
            "style": "../style/terrain_style.xml",
        },
        "scene_name": "myoassist_ensemble",
        "output": "images/myoassist_ensemble.png",
        "render": {
            "width": 3840,
            "height": 2160,
            "camera": CAMERAS,
        },
        "velocity_map": {
            "terrain_config": "../configs/myoassist_base.json",
            "samples_per_tile": 10,
            "mode": "tile",
            "tile_radial_mode": "mixed",
            "start": [0.0, 0.0, 0.0],
            "goal": [1.0, 0.0, 0.0],
        },
        "models": models,
    }

    OUT_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    n_instances = sum(len(m["instances"]) for m in models)
    print(f"\nWrote {OUT_PATH} with {n_instances} instances across {len(models)} models and {len(CAMERAS)} cameras.")

    # Tiled config: same camera bank, but each instance is replicated 9x
    # (one per 3x3 block of the 9x9 tiled terrain) with position rotated
    # and translated to match the block's rotation.
    tiled_models = []
    for entry in models:
        tiled_instances = []
        for inst in entry["instances"]:
            for new_qpos in transpose_to_blocks(inst["qpos"]):
                tiled_instances.append({"qpos": new_qpos})
        tiled_models.append(
            {
                "name": entry["name"],
                "model": entry["model"],
                "instances": tiled_instances,
            }
        )

    tiled_config = {
        "_comment": (
            "9x9 tiled version: each pose from the small-base config is "
            "transposed onto all 9 blocks, with horizontal (qpos[0], qpos[2]) "
            "and pelvis_rotation (qpos[5]) rotated to match the per-block "
            "rotations. Block rotations are pinned to master_seed=42 in "
            "_make_tiled.py — re-run that script with the same seed before "
            "rendering, otherwise model placements will desync from the "
            "rotated tiles. Open via "
            "`python -m myoassist_terrains set-active myoassist_base_tiled3x3` then "
            "`python render_ensemble.py --config myoassist_ensemble_tiled_config.json`."
        ),
        "terrain_build": {
            "config": "../configs/myoassist_tiled.json",
            "style": "../style/terrain_style.xml",
        },
        "scene_name": "myoassist_ensemble_tiled",
        "output": "images/myoassist_ensemble_tiled.png",
        "render": {
            "width": 3840,
            "height": 2160,
            "camera": CAMERAS,
        },
        "velocity_map": {
            "terrain_config": "../configs/myoassist_tiled.json",
            "samples_per_tile": 10,
            "mode": "tile",
            "tile_radial_mode": "mixed",
            "start": [0.0, 0.0, 0.0],
            "goal": [1.0, 0.0, 0.0],
        },
        "models": tiled_models,
    }

    TILED_OUT_PATH.write_text(json.dumps(tiled_config, indent=2), encoding="utf-8")
    n_tiled_instances = sum(len(m["instances"]) for m in tiled_models)
    print(f"Wrote {TILED_OUT_PATH} with {n_tiled_instances} instances ({n_instances} poses x 9 blocks).")


if __name__ == "__main__":
    main()
