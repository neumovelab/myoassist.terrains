"""Render multiple MuJoCo models posed on a shared terrain.

This script builds a composite MJCF by combining a terrain definition with one
or more models, places multiple instances of each model according to a
configuration file, and renders a single image of the resulting scene.

Run:

  python render_ensemble.py --config ensemble_config.json

"""

from __future__ import annotations

import argparse
import copy
import json
import math
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import mediapy as media
import mujoco
import numpy as np

from myoassist_terrains import build_terrain
from myoassist_terrains.composer import emit_xml_include
from myoassist_terrains.config import load_config
from myoassist_terrains.velocity_arrows import add_velocity_overlay
from myoassist_terrains.velocity_map import generate_velocity_map


def _find_elements_with_class(node: ET.Element, class_name: str, path: str = "") -> List[str]:
    """Recursively find all elements that reference a specific class."""
    results = []
    current_class = node.attrib.get("class", "")
    current_tag = node.tag
    if current_class == class_name:
        results.append(f"{path}/{current_tag}[class='{class_name}']")
    for child in node:
        child_path = f"{path}/{current_tag}" if path else current_tag
        results.extend(_find_elements_with_class(child, class_name, child_path))
    return results


def _check_class_references(root: ET.Element, class_name: str) -> List[str]:
    """Check if any elements in the scene reference a specific class."""
    return _find_elements_with_class(root, class_name)


def _deepcopy(elem: ET.Element) -> ET.Element:
    """Shorthand for copy.deepcopy on an ElementTree element."""
    return copy.deepcopy(elem)


def _replace_asset_refs(node: ET.Element, mapping: Dict[str, str]) -> None:
    """Recursively replace attribute values based on the provided mapping."""
    for attr, value in list(node.attrib.items()):
        if value in mapping:
            node.set(attr, mapping[value])
    for child in list(node):
        _replace_asset_refs(child, mapping)


def _apply_suffix_to_names(node: ET.Element, suffix: str) -> None:
    """Append a suffix to the name attribute of node and all descendants."""
    name = node.attrib.get("name")
    if name:
        node.set("name", f"{name}{suffix}")
    for child in list(node):
        _apply_suffix_to_names(child, suffix)


def _replace_site_refs(node: ET.Element, suffix: str) -> None:
    """Replace site references in tendons to match suffixed site names."""
    for child in list(node):
        site_attr = child.attrib.get("site")
        if site_attr:
            child.set("site", f"{site_attr}{suffix}")
        _replace_site_refs(child, suffix)


def _load_terrain(terrain_path: Path, consumer_dir: Path = None) -> Dict[str, List[ET.Element]]:
    """Recursively parse a terrain include file (following <include> tags)
    and return aggregated <asset>, <worldbody>, and <visual> children.

    Path resolution mimics MuJoCo: all relative file paths in the include
    chain resolve relative to the CONSUMER'S directory (the model file's
    location), not to each include file's own directory. `consumer_dir`
    must therefore be set to the directory of whichever model XML loads
    this terrain_config.xml in production. If unset, falls back to the
    terrain file's own directory (which is fine when the terrain file's
    relative paths happen to be self-rooted).
    """
    if consumer_dir is None:
        consumer_dir = terrain_path.parent
    return _gather_terrain_content(terrain_path, consumer_dir)


def _resolve_file_paths(elem: ET.Element, base: Path) -> None:
    """Walk an element tree and rewrite any relative `file=` attributes to
    absolute, anchored at `base`. Uses os.path.abspath instead of resolve()
    to avoid following junctions/symlinks (see _resolve_path docstring)."""
    import os

    file_attr = elem.attrib.get("file")
    if file_attr and not Path(file_attr).is_absolute():
        elem.set("file", os.path.abspath(base / file_attr).replace("\\", "/"))
    for sub in elem:
        _resolve_file_paths(sub, base)


def _gather_terrain_content(file_path: Path, consumer_dir: Path) -> Dict[str, List[ET.Element]]:
    import os

    tree = ET.parse(file_path)
    root = tree.getroot()
    assets: List[ET.Element] = []
    world_children: List[ET.Element] = []
    visual_children: List[ET.Element] = []

    for child in root:
        if child.tag == "include":
            include_file = child.get("file")
            if include_file:
                # MuJoCo-style: resolve relative to the consumer_dir, not
                # the current file's own dir. Use os.path.abspath so the
                # path is normalised without following junctions/symlinks
                # (see _resolve_path docstring).
                included_path = Path(os.path.abspath(consumer_dir / include_file))
                if included_path.exists():
                    sub = _gather_terrain_content(included_path, consumer_dir)
                    assets.extend(sub["assets"])
                    world_children.extend(sub["world"])
                    visual_children.extend(sub.get("visual", []))
        elif child.tag == "asset":
            for c in list(child):
                copied = _deepcopy(c)
                _resolve_file_paths(copied, consumer_dir)
                assets.append(copied)
        elif child.tag == "worldbody":
            for c in list(child):
                copied = _deepcopy(c)
                _resolve_file_paths(copied, consumer_dir)
                world_children.append(copied)
        elif child.tag == "visual":
            for c in list(child):
                visual_children.append(_deepcopy(c))

    return {"assets": assets, "world": world_children, "visual": visual_children}


def _build_styled_terrain(
    terrain_json: Path,
    style_xml: Path,
    work_dir: Path,
) -> Dict[str, List[ET.Element]]:
    """Build styled terrain content from a JSON terrain config.

    Mirrors render_velocity_map.py: builds the procedural terrain spec from
    the config, emits it as an include fragment with absolute hfield/texture
    prefixes (so the PNGs resolve regardless of where the scene compiles),
    then layers in the skybox / materials / visual / lights from
    terrain_style.xml. Returns the same {assets, world, visual} shape as
    _load_terrain so it drops straight into SceneBuilder.add_terrain.

    This is the source of truth for the rendered terrain when a config
    specifies "terrain_build" — it replaces the static terrain_config.xml
    path, which only ever held a flat placeholder floor.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(terrain_json)

    # Resolve the texture file to an absolute path so build_terrain can bind
    # it; check next to the config first, then alongside the style file.
    if config.texture is not None:
        raw = Path(config.texture.file)
        candidates = [
            raw if raw.is_absolute() else terrain_json.parent / raw,
            style_xml.parent / raw.name,
        ]
        existing = next((p for p in candidates if p.exists()), None)
        assert existing is not None, f"texture file not found for {config.texture.file!r}"
        config.texture.file = str(existing.resolve()).replace("\\", "/")

    spec = build_terrain(config, output_dir=work_dir)
    terrain_xml = emit_xml_include(
        spec,
        hfield_relpath_prefix=str(work_dir.resolve()).replace("\\", "/"),
        texture_relpath_prefix=str(style_xml.parent.resolve()).replace("\\", "/"),
    )
    terrain_root = ET.fromstring(terrain_xml)

    assets: List[ET.Element] = []
    world_children: List[ET.Element] = []
    visual_children: List[ET.Element] = []

    # Style first (skybox/materials/visual/lights), then generated geometry.
    style_root = ET.parse(style_xml).getroot()
    for child in style_root:
        if child.tag == "asset":
            assets.extend(list(child))
        elif child.tag == "worldbody":
            world_children.extend(list(child))
        elif child.tag == "visual":
            visual_children.extend(list(child))

    for child in terrain_root:
        if child.tag == "asset":
            assets.extend(list(child))
        elif child.tag == "worldbody":
            world_children.extend(list(child))

    return {"assets": assets, "world": world_children, "visual": visual_children}


class TemplateModel:
    """Holds reusable information for a model MJCF template."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.base_dir = path.parent
        self.xml_tree = ET.parse(path)
        self.xml_root = self.xml_tree.getroot()
        self.model = mujoco.MjModel.from_xml_path(str(path))
        self.nq = self.model.nq
        self.key_qpos: Dict[str, np.ndarray] = {}
        for key_id in range(self.model.nkey):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_KEY, key_id)
            if not name:
                continue
            if self.model.key_qpos.ndim == 2:
                self.key_qpos[name] = self.model.key_qpos[key_id].copy()
            else:
                start = key_id * self.nq
                self.key_qpos[name] = self.model.key_qpos[start : start + self.nq].copy()
        self.joint_qposadr: Dict[str, int] = {}
        for joint_id in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
            if not name:
                continue
            self.joint_qposadr[name] = int(self.model.jnt_qposadr[joint_id])

    def keyframe_qpos(self, key_name: str) -> np.ndarray:
        if key_name not in self.key_qpos:
            raise ValueError(f"Keyframe '{key_name}' not found in template model {self.path}")
        return self.key_qpos[key_name].copy()

    def root_body(self) -> ET.Element:
        worldbody = self.xml_root.find("worldbody")
        if worldbody is None:
            raise ValueError(f"Model {self.path} is missing a worldbody section")
        # Find the first <body> element, skipping cameras, sites, includes, etc.
        for child in worldbody:
            if child.tag == "body":
                return _deepcopy(child)
        raise ValueError(f"Model {self.path} has no body elements in worldbody")

    def asset_elements(self) -> List[ET.Element]:
        asset_node = self.xml_root.find("asset")
        if asset_node is None:
            return []
        copied: List[ET.Element] = []
        for child in list(asset_node):
            new_child = _deepcopy(child)
            file_attr = new_child.attrib.get("file")
            if file_attr:
                resolved = (self.base_dir / file_attr).resolve()
                new_child.set("file", resolved.as_posix())
            copied.append(new_child)
        return copied

    def default_elements(self) -> List[ET.Element]:
        default_nodes = self.xml_root.findall("default")
        return [_deepcopy(node) for node in default_nodes]

    def default_class_names(self) -> List[str]:
        """Return list of default class names defined in this model."""
        default_nodes = self.xml_root.findall("default")
        return [node.attrib.get("class", "") for node in default_nodes]

    def tendon_elements(self) -> List[ET.Element]:
        """Extract tendon elements from the model."""
        tendon_node = self.xml_root.find("tendon")
        if tendon_node is None:
            return []
        return [_deepcopy(child) for child in list(tendon_node)]

    def statistic_element(self) -> Optional[ET.Element]:
        """Return the model's <statistic> element if present.

        MuJoCo derives `model.stat.extent` from this element; when absent it
        auto-computes extent from the AABB of all geoms. Visual settings that
        scale by extent (fog distance, shadow clip, etc.) are sensitive to
        this — a humanoid model authored with extent=2.5 will produce wildly
        different fog when dropped into a 78m terrain unless the original
        <statistic> travels with it into the composed scene.
        """
        node = self.xml_root.find("statistic")
        return _deepcopy(node) if node is not None else None


class SceneBuilder:
    def __init__(self, scene_name: str) -> None:
        self.root = ET.Element("mujoco", {"model": scene_name})
        ET.SubElement(self.root, "compiler", {"angle": "radian"})
        ET.SubElement(self.root, "option", {"gravity": "0 0 -9.81", "timestep": "0.002"})
        self.visual_node = ET.SubElement(self.root, "visual")
        self.asset_node = ET.SubElement(self.root, "asset")
        self.added_default_classes: set[str] = set()
        self.worldbody_node = ET.SubElement(self.root, "worldbody")
        self.tendon_node: Optional[ET.Element] = None
        self.clones: List[np.ndarray] = []

    def set_statistic(self, statistic: ET.Element) -> None:
        """Insert/replace a top-level <statistic> element.

        Inserted before <worldbody> so MuJoCo's compiler picks up the
        explicit extent/center rather than auto-computing from terrain AABB.
        """
        # Drop any existing statistic so this call is idempotent.
        for existing in list(self.root.findall("statistic")):
            self.root.remove(existing)
        # Find worldbody index and insert just before it.
        for i, child in enumerate(self.root):
            if child.tag == "worldbody":
                self.root.insert(i, _deepcopy(statistic))
                return
        self.root.append(_deepcopy(statistic))

    def set_framebuffer_size(self, width: int, height: int) -> None:
        """Set the offscreen framebuffer size in the visual element."""
        global_node = self.visual_node.find("global")
        if global_node is None:
            global_node = ET.SubElement(self.visual_node, "global")
        global_node.set("offwidth", str(width))
        global_node.set("offheight", str(height))

    def add_defaults_once(self, defaults: Iterable[ET.Element]) -> None:
        """Add default elements, merging classes from all models."""
        # Find the worldbody element to insert defaults before it
        worldbody_idx = None
        for i, child in enumerate(self.root):
            if child.tag == "worldbody":
                worldbody_idx = i
                break

        for element in defaults:
            class_name = element.attrib.get("class", "")
            if class_name not in self.added_default_classes:
                # Insert defaults before worldbody, or append if worldbody not found
                if worldbody_idx is not None:
                    self.root.insert(worldbody_idx, _deepcopy(element))
                    worldbody_idx += 1  # Update index since we inserted
                else:
                    self.root.append(_deepcopy(element))
                self.added_default_classes.add(class_name)

    def add_terrain(
        self,
        terrain_assets: List[ET.Element],
        terrain_world: List[ET.Element],
        terrain_visual: Optional[List[ET.Element]] = None,
    ) -> None:
        for asset in terrain_assets:
            self.asset_node.append(asset)
        for item in terrain_world:
            self.worldbody_node.append(item)
        if terrain_visual:
            for v in terrain_visual:
                self.visual_node.append(v)

    def add_model_assets(self, alias: str, assets: List[ET.Element]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for asset in assets:
            name = asset.attrib.get("name")
            if name:
                new_name = f"{alias}_{name}"
                mapping[name] = new_name
                asset.set("name", new_name)
        for asset in assets:
            _replace_asset_refs(asset, mapping)
            self.asset_node.append(asset)
        return mapping

    def add_model_instance(
        self,
        alias: str,
        index: int,
        body_template: ET.Element,
        asset_mapping: Dict[str, str],
        instance_qpos: np.ndarray,
    ) -> None:
        body_copy = _deepcopy(body_template)
        _replace_asset_refs(body_copy, asset_mapping)
        suffix = f"_{alias}_{index}"
        _apply_suffix_to_names(body_copy, suffix)
        self.worldbody_node.append(body_copy)
        self.clones.append(instance_qpos.copy())

    def add_camera(self, name: str, pos: List[float], xyaxes: List[float]) -> None:
        """Add a camera element to the worldbody."""
        ET.SubElement(
            self.worldbody_node,
            "camera",
            {"name": name, "pos": " ".join(map(str, pos)), "xyaxes": " ".join(map(str, xyaxes)), "mode": "fixed"},
        )

    def ensure_tendon_node(self) -> ET.Element:
        """Ensure a tendon node exists, creating it if necessary."""
        if self.tendon_node is None:
            # Find where to insert tendon (after worldbody, before actuator if present)
            worldbody_idx = None
            insert_idx = None
            for i, child in enumerate(self.root):
                if child.tag == "worldbody":
                    worldbody_idx = i
                elif child.tag == "actuator" and worldbody_idx is not None:
                    # Insert before actuator
                    insert_idx = i
                    break

            # Create the tendon element
            self.tendon_node = ET.Element("tendon")

            # Insert at the right position
            if insert_idx is not None:
                self.root.insert(insert_idx, self.tendon_node)
            elif worldbody_idx is not None:
                # Insert after worldbody
                self.root.insert(worldbody_idx + 1, self.tendon_node)
            else:
                # Fallback: append before worldbody (shouldn't happen, but safe)
                self.root.append(self.tendon_node)
        return self.tendon_node

    def add_model_tendons(
        self,
        alias: str,
        index: int,
        tendon_elements: List[ET.Element],
    ) -> None:
        """Add tendon elements for a model instance with proper name suffixing."""
        if not tendon_elements:
            return

        tendon_node = self.ensure_tendon_node()
        suffix = f"_{alias}_{index}"

        for tendon_elem in tendon_elements:
            tendon_copy = _deepcopy(tendon_elem)
            # Apply suffix to tendon name
            name = tendon_copy.attrib.get("name")
            if name:
                tendon_copy.set("name", f"{name}{suffix}")
            # Update site references to match suffixed site names
            _replace_site_refs(tendon_copy, suffix)
            tendon_node.append(tendon_copy)

    def to_xml_string(self) -> str:
        return ET.tostring(self.root, encoding="unicode")


def _resolve_path(path: str, base_dir: Path) -> Path:
    """Make `path` absolute, anchored at `base_dir` if relative.

    Uses `os.path.abspath` rather than `Path.resolve()` so directory
    junctions / symlinks are NOT silently rewritten to their target. That
    matters for any consumer setup where models are linked in from another
    tree (a common test-harness pattern on Windows): without this, every
    `../terrain_config.xml` style include resolved against the consumer
    model's parent ends up pointing into the LINK TARGET's directory
    instead of the workspace the user actually set up.
    """
    import os

    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = Path(os.path.abspath(base_dir / path_obj))
    return path_obj


def _load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _build_scene(config_path: Path, camera_index: Optional[int] = None) -> None:
    config = _load_config(config_path)
    base_dir = config_path.parent

    models_cfg: List[dict] = config.get("models", [])
    if not models_cfg:
        raise ValueError("Configuration must include at least one model entry")

    # MuJoCo resolves nested <include> paths relative to the top-level model
    # file's directory. Mirror that here so includes like ../terrain_style.xml
    # resolve correctly when the consumer model lives one directory deeper.
    first_model_path = _resolve_path(models_cfg[0]["model"], base_dir)
    consumer_dir = first_model_path.parent

    # Terrain source: prefer building the real styled terrain from a JSON
    # config ("terrain_build"); fall back to the static include XML
    # ("terrain") for back-compat. temp_dir is where the composed scene is
    # written for compilation (must sit next to any absolute asset paths).
    tb_cfg = config.get("terrain_build")
    if tb_cfg:
        terrain_json = _resolve_path(tb_cfg["config"], base_dir)
        style_xml = _resolve_path(tb_cfg["style"], base_dir)
        terrain_assets_dir = base_dir / f"{config.get('scene_name', 'ensemble')}_terrain_assets"
        terrain = _build_styled_terrain(terrain_json, style_xml, terrain_assets_dir)
        terrain_path = None
    else:
        terrain_path = _resolve_path(config["terrain"], base_dir)
        terrain = _load_terrain(terrain_path, consumer_dir)

    scene_name = config.get("scene_name", "ensemble_scene")
    builder = SceneBuilder(scene_name)
    builder.add_terrain(terrain["assets"], terrain["world"], terrain.get("visual", []))

    model_templates: Dict[str, TemplateModel] = {}

    for model_index, model_cfg in enumerate(models_cfg):
        alias = model_cfg.get("name")
        if not alias:
            raise ValueError("Each model entry must include a 'name'")
        model_path = _resolve_path(model_cfg["model"], base_dir)
        print(f"Processing model '{alias}' from {model_path}")
        template = TemplateModel(model_path)
        model_templates[alias] = template

        # Carry the first model's <statistic> element into the composed scene
        # so model.stat.extent matches what the same model has when opened
        # standalone in the visualizer. Without this, MuJoCo auto-computes
        # extent from the terrain AABB (~110m for the 78m grid) which makes
        # vis.map.fogstart/fogend (units of extent) produce fog distances
        # 40-50x larger than intended, pushing fog beyond all geometry.
        if model_index == 0:
            stat_elem = template.statistic_element()
            if stat_elem is not None:
                builder.set_statistic(stat_elem)

        # Order matters: add assets FIRST so we know how their names get
        # prefixed, then remap any references inside this model's <default>
        # elements before adding them. Some variant models (e.g. OSL_KA)
        # declare a `<default class="coll"><geom material="MatSkin"/></default>`
        # — without this remap, the `material="MatSkin"` reference inside the
        # default keeps pointing at the un-prefixed asset name and MuJoCo
        # fails to find it at compile time. `add_defaults_once` then dedupes
        # by class name, so subsequent models inherit the first model's
        # (already-remapped) defaults.
        asset_mapping = builder.add_model_assets(alias, template.asset_elements())

        default_elems = template.default_elements()
        for d in default_elems:
            _replace_asset_refs(d, asset_mapping)
        builder.add_defaults_once(default_elems)

        body_template = template.root_body()

        # Check for 'coll' class references in this model's body
        coll_refs = _check_class_references(body_template, "coll")
        if coll_refs:
            print(f"  WARNING: Model '{alias}' body references 'coll' class at: {coll_refs[:3]}...")

        tendon_elements = template.tendon_elements()
        # if tendon_elements:
        # print(f"  Model '{alias}' has {len(tendon_elements)} tendon elements")

        instances = model_cfg.get("instances", [])
        if not instances:
            raise ValueError(f"Model '{alias}' requires at least one instance")

        for index, instance in enumerate(instances):
            custom_qpos = instance.get("qpos")
            if custom_qpos is not None:
                qpos = np.array(custom_qpos, dtype=float, copy=True)
                if qpos.ndim != 1 or qpos.size != template.nq:
                    raise ValueError(f"Custom qpos for '{alias}' instance {index} must have length {template.nq}")
            else:
                key_name = instance.get("keyframe", model_cfg.get("keyframe"))
                if not key_name:
                    raise ValueError(f"Model '{alias}' instance {index} missing keyframe")
                qpos = template.keyframe_qpos(key_name)

                root_joints = model_cfg.get("root_joints", {})
                pos = instance.get("pos")
                if pos is not None:
                    if len(pos) != 3:
                        raise ValueError("Instance 'pos' must be [x, y, z]")
                    for axis, value in zip(("x", "y", "z"), pos):
                        joint_name = root_joints.get(axis)
                        if joint_name:
                            idx = template.joint_qposadr.get(joint_name)
                            if idx is None:
                                raise ValueError(f"Joint '{joint_name}' not found in model {model_path}")
                            if idx >= len(qpos):
                                print(
                                    f"Warning: joint '{joint_name}' index {idx} exceeds qpos length"
                                    f" {len(qpos)} for model {model_path}; skipping translation."
                                )
                            else:
                                qpos[idx] = float(value)
                yaw_deg = instance.get("yaw_deg")
                if yaw_deg is not None:
                    joint_name = root_joints.get("yaw")
                    if not joint_name:
                        raise ValueError(f"Instance for '{alias}' specifies yaw_deg but no 'yaw' joint provided")
                    idx = template.joint_qposadr.get(joint_name)
                    if idx is None or idx >= len(qpos):
                        print(
                            f"Warning: yaw joint '{joint_name}' not available for model {model_path}; skipping yaw adjustment."
                        )
                    else:
                        qpos[idx] = math.radians(float(yaw_deg))

            builder.add_model_instance(alias, index, body_template, asset_mapping, qpos)
            # Add tendons for this instance
            builder.add_model_tendons(alias, index, tendon_elements)

    # Optional velocity-map overlay
    vm_cfg = config.get("velocity_map")
    if vm_cfg:
        vm_terrain_path = _resolve_path(vm_cfg["terrain_config"], base_dir)
        vm_terrain = load_config(vm_terrain_path)
        vm_start = tuple(vm_cfg.get("start", [0.0, 0.0, 0.0]))
        vm_goal = tuple(vm_cfg.get("goal", [1.0, 0.0, 0.0]))
        samples = generate_velocity_map(
            vm_terrain,
            start=vm_start,
            goal=vm_goal,
            samples_per_tile=int(vm_cfg.get("samples_per_tile", 10)),
            mode=str(vm_cfg.get("mode", "tile")),
            tile_radial_mode=str(vm_cfg.get("tile_radial_mode", "mixed")),
            tile_speed_jitter=float(vm_cfg.get("tile_speed_jitter", 0.0)),
            tile_jitter_seed=int(vm_cfg.get("tile_jitter_seed", 0)),
        )
        add_velocity_overlay(
            builder.worldbody_node,
            builder.asset_node,
            samples,
            emission=float(vm_cfg.get("arrow_emission", 0.0)),
        )
        print(f"Velocity overlay: {len(samples)} samples across {len(vm_terrain.tiles)} tiles")

    # Set framebuffer size before compiling (needed for rendering)
    render_cfg = config.get("render", {})
    width = int(render_cfg.get("width", 1920))
    height = int(render_cfg.get("height", 1080))
    builder.set_framebuffer_size(width, height)

    # Parse camera configuration - support both single camera (dict) and multiple cameras (list)
    camera_cfg = render_cfg.get("camera", {})
    cameras_list = []
    if isinstance(camera_cfg, list):
        # Multiple cameras provided as a list
        cameras_list = camera_cfg
    elif isinstance(camera_cfg, dict) and "pos" in camera_cfg and "xyaxes" in camera_cfg:
        # Single camera provided as a dict
        cameras_list = [camera_cfg]

    # Add cameras to XML
    for idx, cam in enumerate(cameras_list):
        if "pos" in cam and "xyaxes" in cam:
            camera_name = f"render_camera_{idx}"
            builder.add_camera(camera_name, cam["pos"], cam["xyaxes"])

    if not cameras_list:
        print("Warning: No cameras specified in config")

    final_xml = builder.to_xml_string()

    # Debug: Save XML for inspection
    debug_xml_path = base_dir / "debug_ensemble_scene.xml"
    print(f"\nSaving generated XML to {debug_xml_path} for inspection")
    with open(debug_xml_path, "w", encoding="utf-8") as f:
        f.write(final_xml)
    # print(f"Final scene has default classes: {sorted(builder.added_default_classes)}")

    # Check for 'coll' class references in the final scene
    coll_refs = _check_class_references(builder.root, "coll")
    if coll_refs:
        print(f"WARNING: Scene contains {len(coll_refs)} elements referencing 'coll' class")
        if "coll" not in builder.added_default_classes:
            print("ERROR: 'coll' class is referenced but not defined in defaults!")
            print("First few references:", coll_refs[:5])

    # Compile the scene by writing a temporary MJCF. In terrain_build mode all
    # asset paths are absolute, so any writable dir works; fall back to the
    # config dir. For the static-include path, write next to the terrain XML
    # so its relative asset paths still resolve.
    temp_dir = terrain_path.parent if terrain_path is not None else base_dir
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", dir=temp_dir, delete=False) as tmp_file:
        tmp_file.write(final_xml)
        tmp_path = Path(tmp_file.name)

    print("\nAttempting to compile MuJoCo model...")
    try:
        scene_model = mujoco.MjModel.from_xml_path(str(tmp_path))
    except Exception as e:
        print(f"ERROR during model compilation: {e}")
        print(f"Check the debug XML file at: {debug_xml_path}")
        raise
    finally:
        tmp_path.unlink(missing_ok=True)

    if not builder.clones:
        raise RuntimeError("No model instances were added to the scene")

    total_nq = sum(len(qpos) for qpos in builder.clones)
    if total_nq != scene_model.nq:
        raise RuntimeError(f"Mismatch between aggregated nq={total_nq} and compiled model nq={scene_model.nq}")

    data = mujoco.MjData(scene_model)
    qpos_vector = np.concatenate(builder.clones)
    data.qpos[:] = qpos_vector
    mujoco.mj_forward(scene_model, data)

    # MuJoCo's Renderer caps the visual-geom buffer at max_geom (default 10k).
    # The ensemble scenes can run far over that (each humanoid is ~160 collision
    # geoms PLUS many visual decorations from tendons, sites, contact pairs,
    # lights, etc., so the effective visual-geom count per humanoid is closer
    # to ~250). 189 humanoids + ~1200 terrain geoms easily exceeds 50k. Size
    # from the compiled model with generous headroom; configurable via
    # render.max_geom in the JSON.
    default_max_geom = max(scene_model.ngeom * 6, 80000)
    max_geom = int(render_cfg.get("max_geom", default_max_geom))
    renderer = mujoco.Renderer(scene_model, width=width, height=height, max_geom=max_geom)

    # Enable optional render flags. We turn fog/shadow/etc. on by default so
    # the visual settings in terrain_style.xml take effect; the render config
    # can override via {"render": {"flags": {"fog": false, ...}}}.
    flag_defaults = {
        "fog": True,
        "haze": True,
        "shadow": True,
        "reflection": True,
        "skybox": True,
    }
    flag_cfg = render_cfg.get("flags", {}) or {}
    flag_lookup = {
        "fog": mujoco.mjtRndFlag.mjRND_FOG,
        "haze": mujoco.mjtRndFlag.mjRND_HAZE,
        "shadow": mujoco.mjtRndFlag.mjRND_SHADOW,
        "reflection": mujoco.mjtRndFlag.mjRND_REFLECTION,
        "skybox": mujoco.mjtRndFlag.mjRND_SKYBOX,
        "wireframe": mujoco.mjtRndFlag.mjRND_WIREFRAME,
        "additive": mujoco.mjtRndFlag.mjRND_ADDITIVE,
    }
    for flag_name, default_on in flag_defaults.items():
        flag_value = bool(flag_cfg.get(flag_name, default_on))
        renderer.scene.flags[flag_lookup[flag_name]] = 1 if flag_value else 0
    for flag_name, flag_value in flag_cfg.items():
        if flag_name in flag_defaults:
            continue
        if flag_name not in flag_lookup:
            print(f"Warning: unknown render flag '{flag_name}', ignoring")
            continue
        renderer.scene.flags[flag_lookup[flag_name]] = 1 if bool(flag_value) else 0

    # Get base output path
    base_output_path = render_cfg.get("output", config.get("output"))

    # Render from each camera
    if not cameras_list:
        # Fallback to free camera if no cameras specified
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(scene_model, camera)
        camera_cfg = render_cfg.get("camera", {})
        if isinstance(camera_cfg, dict):
            lookat = camera_cfg.get("lookat")
            if lookat:
                if len(lookat) != 3:
                    raise ValueError("camera.lookat must have 3 values")
                camera.lookat[:] = np.asarray(lookat, dtype=float)
            camera.distance = float(camera_cfg.get("distance", 15.0))
            camera.azimuth = float(camera_cfg.get("azimuth", 135.0))
            camera.elevation = float(camera_cfg.get("elevation", -20.0))

        renderer.update_scene(data, camera=camera)
        image = renderer.render()

        if base_output_path:
            out_path = _resolve_path(base_output_path, base_dir)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            media.write_image(str(out_path), image)
            print(f"Saved render to {out_path}")
        else:
            media.show_image(image)
    else:
        # Render from each camera (or just one, if --camera-index was given)
        for idx, cam_cfg in enumerate(cameras_list):
            if camera_index is not None and idx != camera_index:
                continue
            camera = mujoco.MjvCamera()

            if "pos" in cam_cfg and "xyaxes" in cam_cfg:
                # Use fixed camera mode
                camera_name = f"render_camera_{idx}"
                camera_id = mujoco.mj_name2id(scene_model, mujoco.mjtObj.mjOBJ_CAMERA, camera_name)
                if camera_id >= 0:
                    camera.type = mujoco.mjtCamera.mjCAMERA_FIXED
                    camera.fixedcamid = camera_id

                    print(f"Rendering camera {idx + 1}/{len(cameras_list)}: '{camera_name}' (ID: {camera_id})")
                    # print(f"  Config: pos={cam_cfg['pos']}, xyaxes={cam_cfg['xyaxes']}")
                    # print(f"  Compiled model: pos={cam_pos}")
                else:
                    print(f"Warning: Camera '{camera_name}' not found in model, skipping")
                    continue
            else:
                # Fall back to lookat/distance/azimuth/elevation format
                mujoco.mjv_defaultFreeCamera(scene_model, camera)
                lookat = cam_cfg.get("lookat")
                if lookat:
                    if len(lookat) != 3:
                        raise ValueError(f"Camera {idx}: camera.lookat must have 3 values")
                    camera.lookat[:] = np.asarray(lookat, dtype=float)
                camera.distance = float(cam_cfg.get("distance", 15.0))
                camera.azimuth = float(cam_cfg.get("azimuth", 135.0))
                camera.elevation = float(cam_cfg.get("elevation", -20.0))
                print(f"Rendering camera {idx + 1}/{len(cameras_list)}: free camera mode")

            renderer.update_scene(data, camera=camera)
            image = renderer.render()

            # Generate output filename with camera index
            if base_output_path:
                out_path = _resolve_path(base_output_path, base_dir)
                # Insert camera index before file extension
                # e.g., "images/test2_ensemble.png" -> "images/test2_ensemble_c1.png"
                stem = out_path.stem
                suffix = out_path.suffix
                camera_suffix = f"_c{idx + 1}"
                new_out_path = out_path.parent / f"{stem}{camera_suffix}{suffix}"
                new_out_path.parent.mkdir(parents=True, exist_ok=True)
                media.write_image(str(new_out_path), image)
                print(f"Saved render to {new_out_path}")
            else:
                media.show_image(image)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render ensembles of MuJoCo models")
    parser.add_argument("--config", required=True, help="Path to ensemble JSON config")
    parser.add_argument(
        "--camera-index",
        type=int,
        default=None,
        help="Render only this camera (0-based) instead of all; output keeps _c{index+1}",
    )
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    _build_scene(config_path, camera_index=args.camera_index)


if __name__ == "__main__":
    main()
