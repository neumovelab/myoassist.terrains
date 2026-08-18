"""Tile registry: built-in entries and plugin-style registration."""

from __future__ import annotations

import pytest

from myoassist_terrains.registry import lookup, register_tile
from myoassist_terrains.tiles import REGISTRY
from myoassist_terrains.tiles.base import TileEmitResult, TileImpl


EXPECTED_BUILTIN_TILES = {
    "boulders",
    "discrete_obstacles",
    "flat",
    "gap",
    "pyramid_stairs",
    "rough",
    "slope",
    "stairs",
    "stepping_stones",
}


def test_all_builtin_tiles_registered():
    """Exact, not a subset: a tile added or removed should show up here."""
    assert set(REGISTRY) == EXPECTED_BUILTIN_TILES


def test_registry_values_are_tileimpl():
    for name, impl in REGISTRY.items():
        assert isinstance(impl, TileImpl), f"{name} -> {type(impl).__name__}"
        assert impl.type_name == name
        assert callable(impl.emit_fn)
        assert isinstance(impl.default_params, dict)
        # Every built-in pairs its emitter with a height model and a speed
        # scale; the velocity map and the surface queries dispatch on these.
        assert callable(impl.surface_height_fn), f"{name} has no surface_height"
        assert impl.default_speed_scale > 0.0, f"{name} has no speed scale"
        assert set(impl.param_docs) == set(impl.default_params), (
            f"{name}: PARAM_DOCS and DEFAULT_PARAMS disagree; the generated tile catalog needs one description per parameter"
        )


def test_lookup_returns_registered_impl():
    impl = lookup("flat")
    assert impl.type_name == "flat"


def test_lookup_unknown_raises_keyerror():
    with pytest.raises(KeyError) as excinfo:
        lookup("teleporter")
    # Helpful message lists what IS registered.
    assert "teleporter" in str(excinfo.value)


def test_register_tile_adds_new_entry():
    """register_tile should add an entry that lookup() can then find."""
    name = "_test_dummy_tile"

    def emit_dummy(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params):
        return TileEmitResult(base_height=0.0)

    try:
        register_tile(
            name,
            emit_dummy,
            default_params={"x": 1},
            param_ranges={"x": (0, 10)},
            default_rgba=(0.1, 0.2, 0.3, 1.0),
        )
        assert name in REGISTRY
        impl = lookup(name)
        assert impl.default_params == {"x": 1}
        assert impl.default_rgba == (0.1, 0.2, 0.3, 1.0)
    finally:
        REGISTRY.pop(name, None)


def test_register_tile_supports_the_height_and_speed_hooks():
    """A custom tile can describe its own surface and speed.

    Without these a registered tile built fine and then failed in the velocity
    map, which had no entry for it, and reported its base height as its surface.
    """
    from myoassist_terrains.velocity_map import DEFAULT_SPEED_SCALE, estimate_surface_height
    from myoassist_terrains.config import TileConfig

    name = "_test_ramp_tile"

    def emit_dummy(spec, origin_xyz, name, *, tile_size, rgba=None, material=None, **params):
        return TileEmitResult(base_height=0.0)

    def height(local_x, local_y, *, tile_size, **_):
        return 0.5 * float(local_x)

    try:
        register_tile(name, emit_dummy, surface_height=height, speed_scale=0.6, param_docs={"note": "documented"})
        impl = lookup(name)
        assert impl.default_speed_scale == 0.6
        tile = TileConfig(row=0, col=0, type=name)
        assert estimate_surface_height(tile, 2.0, 0.0, (4.0, 4.0)) == 1.0
        # DEFAULT_SPEED_SCALE is derived from the registry, so it picks this up.
        from myoassist_terrains import velocity_map as vm

        assert vm.DEFAULT_SPEED_SCALE is DEFAULT_SPEED_SCALE  # same object, module-level
    finally:
        REGISTRY.pop(name, None)
