"""Locating external command-line tools, with a bundled fallback.

The pipeline shells out to ffmpeg/ffprobe. We prefer the system binaries (on
PATH) — they are typically newer and ffprobe ships with them — and fall back to
the ffmpeg binary bundled with ``imageio-ffmpeg`` so the tool works after a plain
``uv sync`` with no system install. ``imageio-ffmpeg`` provides ffmpeg only, not
ffprobe; stages must handle a missing ffprobe.
"""

from __future__ import annotations

import shutil
from functools import lru_cache

from video2document.exceptions import V2DError


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Absolute path to an ffmpeg binary (system if present, else bundled)."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001 - surface a clean, actionable error
        raise V2DError(
            "ffmpeg not found: install it (e.g. `sudo apt-get install ffmpeg`) "
            "or run `uv sync` to get the bundled build (imageio-ffmpeg)."
        ) from exc


@lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    """Absolute path to system ffprobe, or ``None`` (no bundled ffprobe exists)."""
    return shutil.which("ffprobe")


def ffmpeg_is_system() -> bool:
    """True if a system ffmpeg is being used (rather than the bundled one)."""
    return shutil.which("ffmpeg") is not None
