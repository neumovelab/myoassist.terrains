"""XML geom utilities for rendering velocity-map arrows in a MuJoCo scene.

Provides a single public entry point, `add_velocity_overlay`, plus the small
helpers it depends on. Both `render_velocity_map.py` and `render_ensemble.py`
import from here so the arrow style stays in one place.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import numpy as np

from myoassist_terrains.velocity_map import VelocitySample


def quat_from_z_axis(vector: np.ndarray) -> tuple[float, float, float, float]:
    """Quaternion that rotates world +Z onto `vector`."""
    norm = float(np.linalg.norm(vector))
    assert norm > 1e-12
    target = vector / norm
    source = np.asarray([0.0, 0.0, 1.0], dtype=float)
    dot = float(np.dot(source, target))
    if dot > 1.0 - 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    if dot < -1.0 + 1e-12:
        return (0.0, 1.0, 0.0, 0.0)
    axis = np.cross(source, target)
    axis /= np.linalg.norm(axis)
    angle = math.acos(dot)
    half = angle / 2.0
    return (
        float(math.cos(half)),
        float(axis[0] * math.sin(half)),
        float(axis[1] * math.sin(half)),
        float(axis[2] * math.sin(half)),
    )


def rgba_for_speed(speed: float, max_speed: float) -> str:
    """Red (slow) → green (fast) RGBA string."""
    assert max_speed > 0.0
    t = max(0.0, min(1.0, speed / max_speed))
    r = 1.0 - t
    g = 0.2 + 0.75 * t
    b = 0.05
    return f"{r:.3f} {g:.3f} {b:.3f} 1"


def cone_mesh(name: str, radius: float, length: float) -> ET.Element:
    """Build a closed cone <mesh> element pointing along +Z."""
    segments = 18
    vertices: list[tuple[float, float, float]] = [(0.0, 0.0, length)]
    vertices.extend(
        (
            radius * math.cos(2.0 * math.pi * i / segments),
            radius * math.sin(2.0 * math.pi * i / segments),
            0.0,
        )
        for i in range(segments)
    )
    vertices.append((0.0, 0.0, 0.0))
    center_idx = len(vertices) - 1

    faces: list[tuple[int, int, int]] = []
    for i in range(segments):
        j = 1 + ((i + 1) % segments)
        faces.append((0, 1 + i, j))
        faces.append((center_idx, j, 1 + i))

    return ET.Element(
        "mesh",
        {
            "name": name,
            "vertex": " ".join(f"{v:.6f}" for xyz in vertices for v in xyz),
            "face": " ".join(str(i) for tri in faces for i in tri),
        },
    )


def add_velocity_overlay(
    worldbody: ET.Element,
    asset: ET.Element,
    samples: list[VelocitySample],
) -> None:
    """Inject velocity-arrow geoms (shaft + cone head) into an existing scene.

    Arrows are non-colliding and coloured red→green by normalised speed.
    Call this after terrain and model geoms are already in `worldbody`/`asset`
    so MuJoCo name-uniqueness checks pass cleanly.
    """
    head_len = 0.22
    head_bins = 8
    for bin_idx in range(head_bins):
        t = bin_idx / (head_bins - 1)
        radius = 0.018 + 0.095 * (t ** 1.5)
        asset.append(cone_mesh(f"velocity_arrow_head_{bin_idx}", radius, head_len))

    max_speed = max(s.speed for s in samples)

    for i, sample in enumerate(samples):
        velocity = np.asarray(sample.velocity, dtype=float)
        speed = float(np.linalg.norm(velocity))
        if speed <= 1e-9:
            continue
        direction = velocity / speed
        speed_ratio = max(0.0, min(1.0, sample.speed / max_speed))
        length = 0.45 + 0.55 * speed_ratio
        shaft_len = max(0.08, length - head_len)
        shaft_radius = 0.005 + 0.045 * (speed_ratio ** 1.5)
        head_bin = min(head_bins - 1, max(0, round(speed_ratio * (head_bins - 1))))
        quat = quat_from_z_axis(direction)
        rgba = rgba_for_speed(sample.speed, max_speed)

        body = ET.SubElement(
            worldbody,
            "body",
            {
                "name": f"velocity_arrow_{i:04d}",
                "pos": (
                    f"{sample.position[0]:.5f} "
                    f"{sample.position[1]:.5f} "
                    f"{sample.position[2]:.5f}"
                ),
                "quat": " ".join(f"{q:.8f}" for q in quat),
            },
        )
        ET.SubElement(
            body,
            "geom",
            {
                "name": f"velocity_arrow_{i:04d}_shaft",
                "type": "cylinder",
                "size": f"{shaft_radius:.5f} {shaft_len / 2.0:.5f}",
                "pos": f"0 0 {shaft_len / 2.0:.5f}",
                "rgba": rgba,
                "contype": "0",
                "conaffinity": "0",
            },
        )
        ET.SubElement(
            body,
            "geom",
            {
                "name": f"velocity_arrow_{i:04d}_head",
                "type": "mesh",
                "mesh": f"velocity_arrow_head_{head_bin}",
                "pos": f"0 0 {shaft_len:.5f}",
                "rgba": rgba,
                "contype": "0",
                "conaffinity": "0",
            },
        )
