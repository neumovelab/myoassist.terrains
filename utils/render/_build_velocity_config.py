"""Build the two full ensemble render configs (+ a smoke config).

Both render on the SAME 9x9 tiled terrain (base_tiled3x3, 5 m tiles);
they differ in model density and the velocity overlay:

  WITH ARROWS  -> ensemble_velocity.json
      base   : ensemble_tiled_config.json       (207 instances, full tiled)
      + velocity_map overlay (tile-mode red->green arrows)
      -> dense, "top-down density" look

  NO ARROWS    -> ensemble_noarrows.json
      base   : ensemble_centered_config.json    (138 instances, centered)
      no overlay
      -> less busy

Model paths ("26muscle_3D/...") and per-base instance qpos/cameras (8 each,
4K) carry over unchanged. Tile color for both reads from
utils/render/terrain_style.xml (skybox/fog/lights); the terrain colour comes from
utils/style/terrain_style.xml.

Re-run after editing poses/cameras/overlay:
  python utils/render/_build_velocity_config.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

TERRAIN_STYLE = "../style/terrain_style.xml"
TILED_TERRAIN = "../configs/base_tiled3x3.json"  # 9x9 x 5 m, both scenes

# Velocity overlay (arrows scene only). Tile centers on the 9x9 grid span
# ~[-23.2, 23.2]; start/goal only bias direction in "tile" mode.
VELOCITY = {
    "terrain_config": TILED_TERRAIN,
    "start": [-22.0, -22.0, 0.0],
    "goal": [22.0, 22.0, 0.0],
    "samples_per_tile": 6,
    "mode": "tile",  # "tile" = per-tile flow field; "goal" = all toward goal
    "tile_radial_mode": "mixed",
}

SMOKE_CAMERA_INDEX = 3


def _tiled(cfg: dict) -> dict:
    cfg = copy.deepcopy(cfg)
    cfg.pop("terrain", None)  # drop static include
    cfg.pop("velocity_map", None)  # callers re-add if wanted
    cfg["terrain_build"] = {"config": TILED_TERRAIN, "style": TERRAIN_STYLE}
    return cfg


def _count(cfg: dict) -> int:
    return sum(len(m.get("instances", [])) for m in cfg.get("models", []))


def main() -> None:
    arrows_base = json.loads((HERE / "ensemble_tiled_config.json").read_text(encoding="utf-8"))
    noarrows_base = json.loads((HERE / "ensemble_centered_config.json").read_text(encoding="utf-8"))

    # --- WITH ARROWS: 207 models, full tiled density ---
    arrows = _tiled(arrows_base)
    arrows["velocity_map"] = copy.deepcopy(VELOCITY)
    arrows["scene_name"] = "ensemble_velocity"
    arrows["output"] = "images/ensemble_velocity.png"
    (HERE / "ensemble_velocity.json").write_text(json.dumps(arrows, indent=2), encoding="utf-8")

    # --- NO ARROWS: 138 centered models, less busy ---
    noarrows = _tiled(noarrows_base)
    noarrows["scene_name"] = "ensemble_noarrows"
    noarrows["output"] = "images/ensemble_noarrows.png"
    (HERE / "ensemble_noarrows.json").write_text(json.dumps(noarrows, indent=2), encoding="utf-8")

    # --- smoke: arrows scene, single camera, low res ---
    smoke = _tiled(arrows_base)
    smoke["velocity_map"] = copy.deepcopy(VELOCITY)
    smoke["velocity_map"]["samples_per_tile"] = 3
    smoke["scene_name"] = "ensemble_velocity_smoke"
    smoke["output"] = "images/ensemble_velocity_smoke.png"
    smoke["render"] = {
        "width": 1280,
        "height": 720,
        "camera": [arrows_base["render"]["camera"][SMOKE_CAMERA_INDEX]],
    }
    (HERE / "ensemble_velocity_smoke.json").write_text(json.dumps(smoke, indent=2), encoding="utf-8")

    print(f"WITH ARROWS : {_count(arrows)} instances, {len(arrows['render']['camera'])} cameras (tiled full)")
    print(f"NO ARROWS   : {_count(noarrows)} instances, {len(noarrows['render']['camera'])} cameras (centered)")
    print("wrote ensemble_velocity.json, ensemble_noarrows.json, ensemble_velocity_smoke.json")


if __name__ == "__main__":
    main()
