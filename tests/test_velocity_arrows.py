"""The arrow overlay, which had no coverage at all despite being public API.

`add_velocity_overlay` is documented in `docs/velocity-maps.md` and is what the
figure pipeline draws with, so the things asserted here are the ones a broken
overlay would get wrong quietly: arrows that collide with the model, arrows
pointing the wrong way, or a scene that no longer compiles.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest

import mujoco

from myoassist_terrains.config import BorderConfig, GridConfig, TerrainConfig, TileConfig
from myoassist_terrains.velocity_arrows import (
    add_velocity_overlay,
    cone_mesh,
    quat_from_z_axis,
    rgba_for_speed,
)
from myoassist_terrains.velocity_map import generate_velocity_map


def _samples(samples_per_tile: int = 3):
    config = TerrainConfig(
        terrain_name="arrows",
        grid=GridConfig(rows=1, cols=2, tile_size=(4.0, 4.0)),
        border=BorderConfig(width=0.0),
        tiles=[
            TileConfig(row=0, col=0, type="flat"),
            TileConfig(row=0, col=1, type="stairs", params={"n_steps": 3}),
        ],
    )
    return generate_velocity_map(config, start=(-4.0, 0.0, 0.0), goal=(6.0, 0.0, 0.0), samples_per_tile=samples_per_tile)


def _scene(samples, **kwargs) -> str:
    root = ET.Element("mujoco", {"model": "arrow_scene"})
    asset = ET.SubElement(root, "asset")
    worldbody = ET.SubElement(root, "worldbody")
    # A ground plane so the scene is a valid model on its own.
    ET.SubElement(worldbody, "geom", {"name": "ground", "type": "plane", "size": "20 20 0.1"})
    add_velocity_overlay(worldbody, asset, samples, **kwargs)
    return ET.tostring(root, encoding="unicode")


def test_overlay_compiles_and_adds_two_geoms_per_arrow():
    samples = _samples()
    model = mujoco.MjModel.from_xml_string(_scene(samples))
    arrows = [i for i in range(model.ngeom) if (model.geom(i).name or "").startswith("velocity_arrow_")]
    # A shaft and a cone head each; samples with no speed are skipped.
    assert len(arrows) == 2 * sum(1 for s in samples if np.linalg.norm(s.velocity) > 1e-9)


def test_arrows_do_not_collide():
    """Arrows are decoration. If they collide they change the physics they describe."""
    model = mujoco.MjModel.from_xml_string(_scene(_samples()))
    for i in range(model.ngeom):
        if (model.geom(i).name or "").startswith("velocity_arrow_"):
            assert model.geom_contype[i] == 0
            assert model.geom_conaffinity[i] == 0


def test_arrow_orientation_follows_the_sample_velocity():
    """The body quaternion has to rotate +z onto the sample's velocity."""
    samples = _samples()
    model = mujoco.MjModel.from_xml_string(_scene(samples))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    drawn = [s for s in samples if np.linalg.norm(s.velocity) > 1e-9]
    for index, sample in enumerate(drawn):
        body = model.body(f"velocity_arrow_{index:04d}")
        local_z = data.xmat[body.id].reshape(3, 3)[:, 2]
        want = np.asarray(sample.velocity) / np.linalg.norm(sample.velocity)
        assert float(np.dot(local_z, want)) == pytest.approx(1.0, abs=1e-5)


def test_emission_switches_arrows_onto_binned_materials():
    plain = mujoco.MjModel.from_xml_string(_scene(_samples()))
    glowing = mujoco.MjModel.from_xml_string(_scene(_samples(), emission=0.6, color_bins=8))
    assert plain.nmat == 0
    assert glowing.nmat == 8
    assert float(glowing.mat_emission.max()) == pytest.approx(0.6)


def test_empty_sample_list_is_reported():
    """It used to die inside min() on an empty sequence."""
    with pytest.raises(ValueError, match="no velocity samples"):
        _scene([])


def test_negative_emission_and_too_few_bins_are_reported():
    with pytest.raises(ValueError, match="emission"):
        _scene(_samples(), emission=-1.0)
    with pytest.raises(ValueError, match="color_bins"):
        _scene(_samples(), emission=0.5, color_bins=1)


# ---------------------------------------------------------------------------
# helpers


@pytest.mark.parametrize(
    "vector",
    [(0.0, 0.0, 1.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.3, -0.7, 0.2)],
)
def test_quat_from_z_axis_rotates_z_onto_the_vector(vector):
    quat = np.asarray(quat_from_z_axis(np.asarray(vector, dtype=float)))
    rotation = np.zeros(9)
    mujoco.mju_quat2Mat(rotation, quat)
    mapped = rotation.reshape(3, 3)[:, 2]
    want = np.asarray(vector, dtype=float)
    want = want / np.linalg.norm(want)
    assert mapped == pytest.approx(want, abs=1e-6)


def test_quat_from_zero_vector_is_reported():
    with pytest.raises(ValueError, match="zero-length"):
        quat_from_z_axis(np.zeros(3))


def test_speed_colour_ramps_red_to_green():
    slow = rgba_for_speed(0.0, 0.0, 1.0).split()
    fast = rgba_for_speed(1.0, 0.0, 1.0).split()
    assert float(slow[0]) > float(slow[1])  # red dominates at the bottom
    assert float(fast[1]) > float(fast[0])  # green dominates at the top


def test_cone_mesh_is_closed_and_points_along_z():
    element = cone_mesh("cone", radius=0.05, length=0.2)
    vertices = np.asarray([float(v) for v in element.get("vertex").split()]).reshape(-1, 3)
    faces = np.asarray([int(i) for i in element.get("face").split()]).reshape(-1, 3)
    assert vertices[:, 2].max() == pytest.approx(0.2)
    assert vertices[:, 2].min() == pytest.approx(0.0)
    # Every vertex is used, so the hull MuJoCo builds has no strays.
    assert set(faces.ravel().tolist()) == set(range(len(vertices)))
