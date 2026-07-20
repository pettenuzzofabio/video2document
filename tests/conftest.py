"""Shared test fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from video2document import tools


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
