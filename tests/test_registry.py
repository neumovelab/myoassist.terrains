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
    assert EXPECTED_BUILTIN_TILES.issubset(REGISTRY)


def test_registry_values_are_tileimpl():
    for name, impl in REGISTRY.items():
        assert isinstance(impl, TileImpl), f"{name} -> {type(impl).__name__}"
        assert impl.type_name == name
        assert callable(impl.emit_fn)
        assert isinstance(impl.default_params, dict)


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
