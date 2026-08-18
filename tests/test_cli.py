"""The CLI and project-path discovery, which had no coverage at all.

Two of the defects this suite now guards lived here precisely because nothing
exercised them: `python -m` reported success for every failure, and `preview`
emitted a scene with no lights because it assumed the generated terrain chained
the style file, which it never did.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import mujoco

from myoassist_terrains.cli import main
from myoassist_terrains.paths import find_terrain_root

REPO = Path(__file__).resolve().parents[1]
STYLE = REPO / "utils" / "style"
CONFIGS = REPO / "utils" / "configs"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal user project: the pointer, the style, and a terrain library."""
    (tmp_path / "terrain").mkdir()
    for name in ("terrain_config.xml", "terrain_style.xml", "CONCRETE.png"):
        (tmp_path / name).write_bytes((STYLE / name).read_bytes())
    (tmp_path / "terrain" / "default.xml").write_bytes((STYLE / "terrain" / "default.xml").read_bytes())
    return tmp_path


def _run_module(project: Path, *args: str) -> subprocess.CompletedProcess:
    """Spawn `python -m myoassist_terrains`.

    Spawned deliberately. An in-process call to `main()` returns the exit code to
    the test regardless of whether `__main__` propagates it, so the M3 defect --
    `python -m` exiting 0 on failure -- was invisible to any in-process check.
    """
    return subprocess.run(
        [sys.executable, "-m", "myoassist_terrains", *args],
        cwd=project,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Exit codes


def test_module_invocation_propagates_failure(project: Path):
    result = _run_module(project, "build", "does_not_exist.json")
    assert result.returncode != 0, (
        "`python -m myoassist_terrains` reported success for a missing config; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "not found" in result.stderr


def test_module_invocation_matches_the_console_script(project: Path, monkeypatch):
    """docs/cli.md calls the two equivalent, so their exit codes must agree."""
    spawned = _run_module(project, "set-active", "no_such_terrain")
    monkeypatch.chdir(project)
    in_process = main(["set-active", "no_such_terrain"])
    assert spawned.returncode == in_process != 0


def test_module_invocation_succeeds_on_a_good_build(project: Path):
    result = _run_module(project, "build", str(CONFIGS / "flat_smoke_test.json"))
    assert result.returncode == 0, result.stderr
    assert (project / "terrain" / "flat_smoke_test.xml").exists()


# ---------------------------------------------------------------------------
# build / set-active / list


def test_build_then_activate_rewrites_the_pointer(project: Path, monkeypatch):
    monkeypatch.chdir(project)
    assert main(["build", str(CONFIGS / "flat_smoke_test.json"), "--activate"]) == 0
    pointer = (project / "terrain_config.xml").read_text(encoding="utf-8")
    assert "../terrain/flat_smoke_test.xml" in pointer


def test_activate_failure_is_reported_by_build(project: Path, monkeypatch):
    """`build --activate` used to discard the activate step's exit code."""
    monkeypatch.chdir(project)
    (project / "terrain_config.xml").write_text("<mujocoinclude/>\n", encoding="utf-8")
    assert main(["build", str(CONFIGS / "flat_smoke_test.json"), "--activate"]) != 0


def test_list_marks_the_active_terrain(project: Path, monkeypatch, capsys):
    monkeypatch.chdir(project)
    main(["build", str(CONFIGS / "flat_smoke_test.json"), "--activate"])
    capsys.readouterr()
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "* flat_smoke_test.xml" in out
    assert "Registered tile types" in out


def test_root_flag_works_from_an_unrelated_directory(project: Path, tmp_path: Path, monkeypatch):
    """Without --root, build has to be run from inside a project tree."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["build", str(CONFIGS / "flat_smoke_test.json"), "--root", str(project)]) == 0
    assert (project / "terrain" / "flat_smoke_test.xml").exists()


# ---------------------------------------------------------------------------
# preview


def test_preview_is_a_loadable_lit_scene(project: Path, monkeypatch):
    """The preview used to compile with zero lights and zero textures."""
    monkeypatch.chdir(project)
    assert main(["build", str(CONFIGS / "flat_smoke_test.json")]) == 0
    assert main(["preview", "flat_smoke_test"]) == 0

    wrapper = project / "terrain" / "flat_smoke_test_preview.xml"
    assert "../terrain_style.xml" in wrapper.read_text(encoding="utf-8")

    model = mujoco.MjModel.from_xml_path(str(wrapper))
    assert model.ngeom > 0
    assert model.nlight > 0, "preview scene has no lights, so it renders unlit"
    assert model.ntex > 0, "preview scene has no textures, so it has no skybox"
    # Big enough to render QC images without hitting the 640x480 default.
    assert model.vis.global_.offwidth >= 1920


def test_preview_still_works_without_a_style_file(project: Path, monkeypatch):
    monkeypatch.chdir(project)
    main(["build", str(CONFIGS / "flat_smoke_test.json")])
    (project / "terrain_style.xml").unlink()
    assert main(["preview", "flat_smoke_test"]) == 0
    model = mujoco.MjModel.from_xml_path(str(project / "terrain" / "flat_smoke_test_preview.xml"))
    assert model.ngeom > 0


def test_preview_rejects_an_unknown_terrain(project: Path, monkeypatch):
    monkeypatch.chdir(project)
    assert main(["preview", "not_built"]) == 2


# ---------------------------------------------------------------------------
# paths.py


def test_root_discovery_walks_up(project: Path):
    nested = project / "models" / "deep"
    nested.mkdir(parents=True)
    assert find_terrain_root(nested) == project.resolve()


def test_root_discovery_reports_where_it_looked(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="terrain_config.xml"):
        find_terrain_root(tmp_path)


@pytest.mark.parametrize("var", ["MYOASSIST_TERRAINS_ROOT", "MYO_TERRAIN_ROOT"])
def test_env_override_is_honoured(project: Path, tmp_path: Path, monkeypatch, var):
    """The legacy alias is documented as still working, so it is tested."""
    monkeypatch.setenv(var, str(project))
    assert find_terrain_root(tmp_path) == project.resolve()


def test_env_override_rejects_a_directory_without_the_pointer(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MYOASSIST_TERRAINS_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="does not contain"):
        find_terrain_root()
