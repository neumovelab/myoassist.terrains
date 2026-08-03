"""Render a terrain-only velocity map overlay.

Example:
  python utils/render/render_velocity_map.py \
    --terrain-config utils/configs/myoassist_base.json \
    --start -10 -10 0 \
    --goal 10 10 0
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import mediapy as media
import mujoco
import numpy as np

from myoassist_terrains import build_terrain
from myoassist_terrains.composer import emit_xml_include
from myoassist_terrains.config import load_config
from myoassist_terrains.velocity_arrows import add_velocity_overlay as _add_velocity_overlay
from myoassist_terrains.velocity_map import VelocitySample, generate_velocity_map


def _prepare_config_texture(config_path: Path, output_dir: Path):
    config = load_config(config_path)
    if config.texture is not None:
        raw = Path(config.texture.file)
        candidates = [
            raw if raw.is_absolute() else config_path.parent / raw,
            config_path.parents[1] / "style" / raw.name,
            output_dir.parent / raw,
        ]
        existing = next((p for p in candidates if p.exists()), None)
        assert existing is not None, f"texture file not found for {config.texture.file!r}"
        config.texture.file = str(existing.resolve()).replace("\\", "/")
    return config


def render_velocity_map(
    terrain_config: Path,
    output: Path,
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    samples_per_tile: int,
    width: int,
    height: int,
    mode: str,
    tile_radial_mode: str,
) -> None:
    root = Path.cwd()
    output = output.resolve()
    work_dir = output.parent / f"{output.stem}_assets"
    work_dir.mkdir(parents=True, exist_ok=True)

    config = _prepare_config_texture(terrain_config, work_dir)
    samples = generate_velocity_map(
        config,
        start=start,
        goal=goal,
        samples_per_tile=samples_per_tile,
        mode=mode,
        tile_radial_mode=tile_radial_mode,
    )
    spec = build_terrain(config, output_dir=work_dir)
    terrain_xml = emit_xml_include(
        spec,
        hfield_relpath_prefix=str(work_dir.resolve()).replace("\\", "/"),
        texture_relpath_prefix=str((root / "utils" / "style").resolve()).replace("\\", "/"),
    )
    terrain_root = ET.fromstring(terrain_xml)

    scene = ET.Element("mujoco", {"model": f"{config.terrain_name}_velocity_map"})
    ET.SubElement(scene, "compiler", {"angle": "radian"})
    visual = ET.SubElement(scene, "visual")
    ET.SubElement(visual, "global", {"offwidth": str(width), "offheight": str(height)})
    ET.SubElement(visual, "map", {"zfar": "140"})
    ET.SubElement(
        visual,
        "headlight",
        {
            "ambient": "0.35 0.35 0.35",
            "diffuse": "0.75 0.75 0.75",
            "specular": "0.25 0.25 0.25",
        },
    )

    asset = ET.SubElement(scene, "asset")
    worldbody = ET.SubElement(scene, "worldbody")
    ET.SubElement(
        worldbody,
        "light",
        {
            "name": "velocity_key_light",
            "pos": "-8 -6 18",
            "dir": "0.4 0.35 -1",
            "directional": "true",
            "diffuse": "0.9 0.9 0.85",
            "specular": "0.25 0.25 0.25",
        },
    )
    ET.SubElement(
        worldbody,
        "light",
        {
            "name": "velocity_fill_light",
            "pos": "10 8 12",
            "dir": "-0.5 -0.45 -1",
            "directional": "true",
            "diffuse": "0.45 0.50 0.60",
            "specular": "0.05 0.05 0.05",
        },
    )
    for child in list(terrain_root):
        if child.tag == "asset":
            for asset_child in list(child):
                asset.append(asset_child)
        elif child.tag == "worldbody":
            for world_child in list(child):
                worldbody.append(world_child)
        else:
            scene.append(child)

    ET.SubElement(
        worldbody,
        "site",
        {
            "name": "velocity_start",
            "type": "sphere",
            "pos": f"{start[0]} {start[1]} {start[2] + 0.6}",
            "size": "0.22",
            "rgba": "0.1 0.35 1 1",
        },
    )
    if mode == "goal":
        ET.SubElement(
            worldbody,
            "site",
            {
                "name": "velocity_goal",
                "type": "sphere",
                "pos": f"{goal[0]} {goal[1]} {goal[2] + 0.6}",
                "size": "0.22",
                "rgba": "1 0.1 0.1 1",
            },
        )
    _add_velocity_overlay(worldbody, asset, samples)

    ET.indent(scene, space="  ")
    xml_path = output.with_suffix(".xml")
    ET.ElementTree(scene).write(xml_path, encoding="unicode")

    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, width=width, height=height, max_geom=max(model.ngeom * 6, 30000))
    renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0

    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, camera)
    camera.lookat[:] = np.asarray([0.0, 0.0, 0.6], dtype=float)
    camera.distance = 30.0
    camera.azimuth = 135.0
    camera.elevation = -38.0
    renderer.update_scene(data, camera=camera)
    image = renderer.render()
    output.parent.mkdir(parents=True, exist_ok=True)
    media.write_image(str(output), image)

    print(xml_path)
    print(output)
    print(f"samples {len(samples)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a terrain velocity map overlay")
    parser.add_argument("--terrain-config", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("utils/render/velocity_map/myoassist_base_velocity_map.png"))
    parser.add_argument("--start", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"))
    parser.add_argument("--goal", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"))
    parser.add_argument("--samples-per-tile", type=int, default=10)
    parser.add_argument("--width", type=int, default=1800)
    parser.add_argument("--height", type=int, default=1200)
    parser.add_argument("--mode", choices=("goal", "tile"), default="goal")
    parser.add_argument("--tile-radial-mode", choices=("inward", "outward", "mixed"), default="mixed")
    args = parser.parse_args()

    render_velocity_map(
        terrain_config=args.terrain_config.resolve(),
        output=args.output,
        start=tuple(args.start),
        goal=tuple(args.goal),
        samples_per_tile=args.samples_per_tile,
        width=args.width,
        height=args.height,
        mode=args.mode,
        tile_radial_mode=args.tile_radial_mode,
    )


if __name__ == "__main__":
    main()
