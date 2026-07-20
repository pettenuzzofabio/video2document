"""Shared test fixtures."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from video2document import tools

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tiny_video(tmp_path_factory) -> Path:
    """A tiny, self-contained test video (1s @ 10fps, moving pattern).

    Built with the resolved ffmpeg (system or bundled), so it needs no external
    assets. Frames all differ, so mpdecimate keeps them all.
    """
    path = tmp_path_factory.mktemp("media") / "tiny.mp4"
    subprocess.run(
        [
            tools.ffmpeg_path(), "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def make_fixture(tmp_path_factory):
    """Generate a named synthetic fixture video and return its path.

    Runs scripts/make_fixtures.py in a temp dir (deterministic, no committed assets).
    """

    def _make(name: str) -> Path:
        out = tmp_path_factory.mktemp("fx")
        subprocess.run(
            [
                sys.executable, str(_REPO_ROOT / "scripts" / "make_fixtures.py"),
                "--only", name, "--out", str(out), "--fps", "6",
            ],
            check=True,
            capture_output=True,
            cwd=_REPO_ROOT,
        )
        return out / f"{name}.mp4"

    return _make
