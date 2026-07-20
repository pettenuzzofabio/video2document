"""Stage 1 — decode the video into frames and build the frame manifest.

Planned (M1):
  * ``ffprobe`` the source into ``meta/source.ffprobe.json``.
  * ``ffmpeg`` decode at a capped fps (plus ``mpdecimate`` to drop near-identical
    frames at the source) into ``frames/raw/``, named by presentation timestamp.
  * Write ``manifests/frames.jsonl`` with identity + pts and a *full-frame* hash
    used only to drop exact consecutive duplicates. The authoritative pHash and
    sharpness scores are computed later by the `pages` stage, on cropped frames.
"""

from __future__ import annotations

import logging
from pathlib import Path

from video2document.workspace import Workspace

log = logging.getLogger(__name__)


def run(ws: Workspace, *, video: Path, fps: float) -> None:
    log.warning("stage 'extract' is not implemented yet (arriving in M1)")
    log.info("would decode %s at %g fps into %s", video, fps, ws.frames_raw_dir)
