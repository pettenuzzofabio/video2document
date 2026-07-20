"""Tests for stage 1 (extract): frame extraction, timestamps, metadata."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from video2document import tools
from video2document.exceptions import V2DError
from video2document.stages import extract
from video2document.workspace import Workspace


def test_extract_frames_and_manifest(tmp_path: Path, tiny_video: Path) -> None:
    ws = Workspace(tmp_path / "wd").ensure()
    extract.run(ws, video=tiny_video, fps=5, decimate=False)

    pngs = sorted(ws.frames_raw_dir.glob("*.png"))
    assert len(pngs) >= 4

    lines = ws.frames_manifest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(pngs)

    records = [json.loads(line) for line in lines]
    assert [r["frame_id"] for r in records] == list(range(len(records)))
    pts = [r["pts_ms"] for r in records]
    assert pts == sorted(pts)          # timestamps monotonically increasing
    assert pts[0] == 0.0
    # paths are workspace-relative and point at real files
    assert (ws.root / records[0]["path"]).is_file()

    meta = json.loads(ws.meta_json.read_text(encoding="utf-8"))
    assert meta["prober"] in {"ffprobe", "imageio", "none"}


def test_mpdecimate_drops_static_frames(tmp_path: Path) -> None:
    src = tmp_path / "static.mp4"
    subprocess.run(
        [
            tools.ffmpeg_path(), "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", "color=c=blue:size=320x240:duration=2:rate=10",
            str(src),
        ],
        check=True,
        capture_output=True,
    )
    ws = Workspace(tmp_path / "wd").ensure()
    extract.run(ws, video=src, fps=10, decimate=True)

    pngs = list(ws.frames_raw_dir.glob("*.png"))
    assert 1 <= len(pngs) <= 3  # a static clip collapses to ~1 frame


def test_missing_video_raises(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd").ensure()
    with pytest.raises(V2DError):
        extract.run(ws, video=tmp_path / "nope.mp4", fps=6)


def test_reextract_clears_previous_frames(tmp_path: Path, tiny_video: Path) -> None:
    ws = Workspace(tmp_path / "wd").ensure()
    stale = ws.frames_raw_dir / "999999.png"
    ws.frames_raw_dir.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"stale")
    extract.run(ws, video=tiny_video, fps=5, decimate=False)
    assert not stale.exists()


def test_parse_showinfo() -> None:
    stderr = (
        "[Parsed_showinfo_1 @ 0x1] n:   0 pts:      0 pts_time:0        duration:1\n"
        "[Parsed_showinfo_1 @ 0x1] n:   1 pts:   1000 pts_time:0.500000 duration:1\n"
    )
    assert extract._parse_showinfo(stderr) == {0: 0.0, 1: 500.0}


def test_ffmpeg_resolves() -> None:
    assert Path(tools.ffmpeg_path()).exists()
