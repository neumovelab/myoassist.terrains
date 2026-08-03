"""Terrain(+optional velocity arrows) render with NO musculoskeletal models.

Builds the SAME styled terrain as render_ensemble.py (terrain_build block),
optionally overlays the velocity arrows, and renders from either a fixed camera
defined in the config or a free camera (azimuth/elevation/distance/lookat) for
quick top-down framing. Can also emit the composed scene XML for opening in the
MuJoCo viewer to position cameras by hand.

Examples:
  # top-down preview with arrows
  python utils/render/render_terrain_check.py --config utils/render/terrain5x5_velocity.json \
      --arrows --free --elevation -90 --distance 130 --width 2000 --height 2000

  # emit a viewer-ready XML (then: python -m mujoco.viewer --mjcf=<path>)
  python utils/render/render_terrain_check.py --config utils/render/terrain5x5_velocity.json \
      --arrows --emit-xml utils/render/terrain5x5_viewer.xml

  # render a fixed camera from the config's render.camera list
  python utils/render/render_terrain_check.py --config utils/render/ensemble_velocity.json \
      --camera-index 3
"""
from __future__ import annotations

import argparse
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import mediapy as media
import mujoco
import numpy as np

from myoassist_terrains.config import load_config
from myoassist_terrains.velocity_map import generate_velocity_map

import render_ensemble as RE


def _build(config_path: Path, want_arrows: bool):
    base_dir = config_path.parent
    config = RE._load_config(config_path)

    tb = config["terrain_build"]
    terrain_json = RE._resolve_path(tb["config"], base_dir)
    style_xml = RE._resolve_path(tb["style"], base_dir)
    scene_name = config.get("scene_name", "terrain_check")
    work_dir = base_dir / f"{scene_name}_terrain_assets"
    terrain = RE._build_styled_terrain(terrain_json, style_xml, work_dir)

    builder = RE.SceneBuilder(scene_name + "_terrain")
    builder.add_terrain(terrain["assets"], terrain["world"], terrain.get("visual", []))

    # Borrow a model's <statistic> for sane extent if models are present;
    # otherwise let MuJoCo auto-compute (fog is off, so extent is uncritical).
    models = config.get("models", [])
    if models:
        stat = RE.TemplateModel(RE._resolve_path(models[0]["model"], base_dir)).statistic_element()
        if stat is not None:
            builder.set_statistic(stat)

    if want_arrows:
        vm = config["velocity_map"]
        vm_terrain = load_config(RE._resolve_path(vm["terrain_config"], base_dir))
        samples = generate_velocity_map(
            vm_terrain,
            start=tuple(vm.get("start", [0.0, 0.0, 0.0])),
            goal=tuple(vm.get("goal", [1.0, 0.0, 0.0])),
            samples_per_tile=int(vm.get("samples_per_tile", 6)),
            mode=str(vm.get("mode", "tile")),
            tile_radial_mode=str(vm.get("tile_radial_mode", "mixed")),
            tile_speed_jitter=float(vm.get("tile_speed_jitter", 0.0)),
            tile_jitter_seed=int(vm.get("tile_jitter_seed", 0)),
        )
        RE.add_velocity_overlay(
            builder.worldbody_node, builder.asset_node, samples,
            emission=float(vm.get("arrow_emission", 0.0)),
        )
        print(f"Velocity overlay: {len(samples)} samples")

    return config, base_dir, builder, scene_name


def main() -> None:
    ap = argparse.ArgumentParser(description="Terrain-only render (no MSK models)")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--arrows", action="store_true", help="overlay the velocity map")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    # camera: either a fixed one from the config, or a free camera
    ap.add_argument("--camera-index", type=int, default=None, help="index into render.camera list")
    ap.add_argument("--free", action="store_true", help="use a free camera (azimuth/elevation/distance)")
    ap.add_argument("--azimuth", type=float, default=90.0)
    ap.add_argument("--elevation", type=float, default=-90.0)
    ap.add_argument("--distance", type=float, default=130.0)
    ap.add_argument("--lookat", type=float, nargs=3, default=[0.0, 0.0, 0.0])
    ap.add_argument("--emit-xml", type=Path, default=None, help="write scene XML and skip rendering")
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    config_path = args.config.resolve()
    config, base_dir, builder, scene_name = _build(config_path, args.arrows)
    builder.set_framebuffer_size(args.width, args.height)

    # Disable contacts: this is a static viewing scene, and the dense 15x15
    # terrain (thousands of collidable geoms) overflows the collision broadphase
    # arena when the interactive viewer steps the sim. Harmless for rendering.
    for child in builder.root:
        if child.tag == "option":
            ET.SubElement(child, "flag", {"contact": "disable"})
            break

    # If a fixed camera is requested, register it so the emitted XML carries it.
    fixed_cam_name = None
    if args.camera_index is not None and not args.free:
        cam = config["render"]["camera"][args.camera_index]
        fixed_cam_name = "render_camera_0"
        builder.add_camera(fixed_cam_name, cam["pos"], cam["xyaxes"])

    final_xml = builder.to_xml_string()

    if args.emit_xml is not None:
        args.emit_xml.parent.mkdir(parents=True, exist_ok=True)
        args.emit_xml.write_text(final_xml, encoding="utf-8")
        print(f"Wrote viewer XML: {args.emit_xml}")
        print(f"Open with: python -m mujoco.viewer --mjcf={args.emit_xml.resolve()}")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", dir=base_dir, delete=False) as fh:
        fh.write(final_xml)
        tmp_path = Path(fh.name)
    try:
        model = mujoco.MjModel.from_xml_path(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    data = mujoco.MjData(model)
    # Static scene: only need world poses for rendering. Skip mj_forward (its
    # collision broadphase overflows the arena on the dense 15x15 terrain, which
    # has thousands of collidable geoms). Kinematics + camlight is sufficient.
    mujoco.mj_kinematics(model, data)
    mujoco.mj_camlight(model, data)

    renderer = mujoco.Renderer(model, width=args.width, height=args.height, max_geom=model.ngeom + 20000)
    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_FOG] = 0  # fog disabled for now
    for flag in ("mjRND_HAZE", "mjRND_SHADOW", "mjRND_REFLECTION", "mjRND_SKYBOX"):
        renderer.scene.flags[getattr(mujoco.mjtRndFlag, flag)] = 1

    camera = mujoco.MjvCamera()
    if fixed_cam_name is not None:
        camera.type = mujoco.mjtCamera.mjCAMERA_FIXED
        camera.fixedcamid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, fixed_cam_name)
        tag = f"c{args.camera_index + 1}"
    else:
        mujoco.mjv_defaultFreeCamera(model, camera)
        camera.lookat[:] = np.asarray(args.lookat, dtype=float)
        camera.distance = float(args.distance)
        camera.azimuth = float(args.azimuth)
        camera.elevation = float(args.elevation)
        tag = f"free_az{int(args.azimuth)}_el{int(args.elevation)}"

    renderer.update_scene(data, camera=camera)
    image = renderer.render()

    out = args.output or (base_dir / "images" / f"{scene_name}_{tag}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    media.write_image(str(out), image)
    print(f"Saved {out}  (scene geoms: {model.ngeom})")


if __name__ == "__main__":
    main()
