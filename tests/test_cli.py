"""Smoke tests for the CLI skeleton: the surface exists and stubs run cleanly."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from video2document import __version__
from video2document.cli import app

runner = CliRunner()

SUBCOMMANDS = ["extract", "pages", "transcribe", "assemble", "run"]


def test_root_help_lists_all_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in SUBCOMMANDS:
        assert command in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_subcommand_help(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_extract_stub_creates_workspace(tmp_path) -> None:
    workdir = tmp_path / "work"
    result = runner.invoke(
        app, ["extract", str(tmp_path / "video.mp4"), "--workdir", str(workdir)]
    )
    assert result.exit_code == 0
    # The workspace directory tree is created even though the stage is a stub.
    assert (workdir / "frames" / "raw").is_dir()
    assert (workdir / "manifests").is_dir()
    assert (workdir / "out").is_dir()


def test_run_stub_chains_all_stages(tmp_path) -> None:
    workdir = tmp_path / "work"
    result = runner.invoke(
        app, ["run", str(tmp_path / "video.mp4"), "--workdir", str(workdir)]
    )
    assert result.exit_code == 0
    assert "pipeline complete" in result.output


def test_bad_fps_is_rejected(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["extract", str(tmp_path / "video.mp4"), "--workdir", str(tmp_path), "--fps", "0"],
    )
    assert result.exit_code != 0
