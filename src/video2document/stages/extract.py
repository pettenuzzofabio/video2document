"""Stage 1 — decode the video into frames and build the frame manifest.

Extracts frames at a capped rate (default 6 fps) with ``mpdecimate`` to drop
near-identical frames at the source, names them sequentially, and records each
frame's real presentation timestamp (parsed from ffmpeg's ``showinfo`` filter)
in ``manifests/frames.jsonl``.

This stage only establishes the frame set and their timestamps. The
authoritative pHash / sharpness scores are computed later by the `pages` stage,
on frames cropped to the viewport (scoring raw frames would be diluted by the
static window chrome). See PLAN.md §3.

ffmpeg is the system binary if on PATH, else the one bundled with
``imageio-ffmpeg`` (see :mod:`video2document.tools`). Metadata comes from
ffprobe when available, otherwise from imageio.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from video2document import tools
from video2document.exceptions import V2DError
from video2document.workspace import Workspace

log = logging.getLogger(__name__)

# showinfo logs one line per frame that passes through it:
#   "... n:   0 pts:      0 pts_time:0       duration: ..."
_SHOWINFO_RE = re.compile(r"n:\s*(\d+).*?pts_time:\s*([0-9]+(?:\.[0-9]+)?)")


def run(ws: Workspace, *, video: Path, fps: float, decimate: bool = True) -> None:
    src = Path(video).expanduser().resolve()
    if not src.is_file():
        raise V2DError(f"video not found: {src}")
    ws.ensure()

    _link_source(ws, src)

    meta, raw_ffprobe = _probe(src)
    ws.meta_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if raw_ffprobe is not None:
        ws.ffprobe_json.write_text(json.dumps(raw_ffprobe, indent=2), encoding="utf-8")

    frames = _extract_frames(ws, src, fps=fps, decimate=decimate)
    _write_manifest(ws, frames)

    engine = "system" if tools.ffmpeg_is_system() else "bundled (imageio-ffmpeg)"
    log.info(
        "extracted %d frames at %g fps%s using %s ffmpeg -> %s",
        len(frames), fps, " + mpdecimate" if decimate else "", engine, ws.frames_raw_dir,
    )
    if not frames:
        raise V2DError("no frames extracted; is the video a valid, readable file?")


def _link_source(ws: Workspace, src: Path) -> None:
    """Best-effort provenance link (no data copy). Never fatal."""
    link = ws.source_video(src.suffix.lower() or ".mp4")
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(src)
    except OSError as exc:
        log.debug("could not symlink source (%s); recording path instead", exc)
        (ws.input_dir / "source_path.txt").write_text(f"{src}\n", encoding="utf-8")


def _probe(video: Path) -> tuple[dict, dict | None]:
    """Return (normalized metadata, raw ffprobe json or None)."""
    ffprobe = tools.ffprobe_path()
    if ffprobe:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            raw = json.loads(proc.stdout)
            return {"prober": "ffprobe", **_normalize_ffprobe(raw, video)}, raw
        log.warning("ffprobe failed (exit %d); falling back to imageio", proc.returncode)

    try:
        import imageio

        reader = imageio.get_reader(str(video))
        meta = reader.get_meta_data()
        reader.close()
        width, height = meta.get("size") or (0, 0)
        return {
            "prober": "imageio",
            "fps": meta.get("fps"),
            "duration_s": meta.get("duration"),
            "width": int(width),
            "height": int(height),
            "size_bytes": video.stat().st_size,
        }, None
    except Exception as exc:  # noqa: BLE001 - metadata is best-effort, never fatal
        log.warning("metadata probe failed (%s); continuing without it", exc)
        return {"prober": "none", "size_bytes": video.stat().st_size}, None


def _normalize_ffprobe(raw: dict, video: Path) -> dict:
    stream = next(
        (s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    fps = None
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/0"
    try:
        num, den = rate.split("/")
        fps = round(float(num) / float(den), 4) if float(den) else None
    except (ValueError, ZeroDivisionError):
        fps = None
    fmt = raw.get("format", {})
    return {
        "fps": fps,
        "duration_s": float(fmt["duration"]) if fmt.get("duration") else None,
        "width": stream.get("width"),
        "height": stream.get("height"),
        "size_bytes": int(fmt["size"]) if fmt.get("size") else video.stat().st_size,
    }


def _extract_frames(
    ws: Workspace, video: Path, *, fps: float, decimate: bool
) -> list[tuple[Path, float]]:
    raw_dir = ws.frames_raw_dir
    for old in raw_dir.glob("*.png"):
        old.unlink()

    chain = [f"fps={fps}"]
    if decimate:
        chain.append("mpdecimate")
    chain.append("showinfo")
    cmd = [
        tools.ffmpeg_path(), "-hide_banner", "-nostdin", "-y",
        "-i", str(video),
        "-vf", ",".join(chain),
        "-vsync", "vfr",
        "-start_number", "0",
        str(raw_dir / "%06d.png"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise V2DError("ffmpeg frame extraction failed:\n" + proc.stderr[-1500:])

    pts_by_index = _parse_showinfo(proc.stderr)
    files = sorted(raw_dir.glob("*.png"))
    if pts_by_index and len(pts_by_index) != len(files):
        log.warning(
            "showinfo reported %d frames but %d PNGs were written; "
            "using fps-derived timestamps where needed",
            len(pts_by_index), len(files),
        )

    frames: list[tuple[Path, float]] = []
    for index, path in enumerate(files):
        pts_ms = pts_by_index.get(index)
        if pts_ms is None:
            pts_ms = round(index * 1000.0 / fps, 3)
        frames.append((path, pts_ms))
    return frames


def _parse_showinfo(stderr: str) -> dict[int, float]:
    """Map post-filter frame index -> pts in milliseconds, from showinfo output."""
    result: dict[int, float] = {}
    for match in _SHOWINFO_RE.finditer(stderr):
        result[int(match.group(1))] = round(float(match.group(2)) * 1000.0, 3)
    return result


def _write_manifest(ws: Workspace, frames: list[tuple[Path, float]]) -> None:
    with ws.frames_manifest.open("w", encoding="utf-8") as fh:
        for frame_id, (path, pts_ms) in enumerate(frames):
            record = {
                "frame_id": frame_id,
                "pts_ms": pts_ms,
                "path": str(path.relative_to(ws.root)),
            }
            fh.write(json.dumps(record) + "\n")
