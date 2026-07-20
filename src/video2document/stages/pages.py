"""Stage 2 — turn frames into one clean image per page.

Pipeline (see PLAN.md §3):

1. **Viewport** (once): the stable document region — the axis-aligned rectangle
   whose pixels change across frames (content scrolls) while the window chrome
   stays static. Found by per-pixel temporal variance over sampled frames.
2. **Crop** every frame to the viewport (into ``frames/cropped/``).
3. **Runs**: group consecutive frames that stay pHash-similar to the run's anchor.
   A run is a period the view was stable.
4. **Classify** runs by *persistence* (how long the view stayed put, read from pts
   gaps — mpdecimate collapses a dwell to one frame, so cluster size alone is not
   enough): a run held for >= ``min_page_ms`` is a page, briefer runs are scroll
   transitions and are discarded. No stable run at all ⇒ continuous scroll (fail loud).
5. **Best frame** per page run: sharpest (variance of Laplacian), mid-run on ties.
6. **Revisit merge**: page runs whose best frames look alike (back-scrolling revisits
   a page) collapse into one page; pages are ordered by first appearance.

Heavy libraries (cv2, numpy, PIL, imagehash) are imported lazily so the CLI stays
fast to start.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from video2document.exceptions import V2DError
from video2document.workspace import Workspace

log = logging.getLogger(__name__)

# viewport detection
_SAMPLE_CAP = 80          # max frames sampled for the variance map
_SMALL_W = 480            # downscale width for the variance computation
_MIN_STD = 4.0            # min per-pixel stddev (0-255) to consider "changing"
_CLOSE_K = 15             # morphological close kernel (small coords) — bridge text
_OPEN_K = 3               # open kernel — drop speckle
_PAD_FRAC = 0.02          # pad the detected rect outward by this fraction
_MIN_AREA_FRAC = 0.02     # reject a viewport smaller than this fraction of the frame


def run(
    ws: Workspace,
    *,
    viewport: str = "auto",
    hamming: int = 6,
    ssim: float = 0.985,  # reserved for the optional SSIM merge pass (not used in v1)
    min_page_ms: float = 400.0,
    mode: str = "pagefit",
    rotate: str = "none",
) -> None:
    frames = _load_frames(ws)
    if not frames:
        raise V2DError("no frames found — run `v2d extract` first")

    duration_ms = _duration_ms(ws, frames)

    rect, method = _detect_viewport(ws, frames, viewport)
    _write_viewport(ws, rect, method, frames)
    log.info("viewport (%s): x=%d y=%d w=%d h=%d", method, *rect)

    hashes = _crop_and_score(ws, frames, rect, rotate)

    if mode == "scroll":
        _run_scroll(ws, frames)
        _write_frames_manifest(ws, frames)
        return

    _compute_persistence(frames, duration_ms)

    runs = _group_runs(hashes, hamming)
    for run_id, members in enumerate(runs):
        for idx in members:
            frames[idx]["run_id"] = run_id

    page_runs = _classify(frames, runs, min_page_ms)
    if not page_runs:
        raise V2DError(
            "no stable pages detected — this looks like continuous scrolling, which "
            "v1 does not support (it needs page-fit: each page fully visible at some "
            "moment). If pages really do pause, lower --min-page-ms."
        )
    for pr in page_runs:
        pr["best_idx"] = _best_frame(frames, pr["frames"])

    distinct = _revisit_merge(page_runs, frames, hashes, hamming)
    distinct.sort(key=lambda d: d["first_pts"])

    _emit_pages(ws, frames, distinct)
    _write_frames_manifest(ws, frames)

    revisits = sum(len(d["revisit_pts"]) for d in distinct)
    log.info(
        "%d frames -> %d page runs -> %d pages%s -> %s",
        len(frames), len(page_runs), len(distinct),
        f" ({revisits} revisit(s) merged)" if revisits else "",
        ws.pages_dir,
    )


# -- loading ------------------------------------------------------------------
def _load_frames(ws: Workspace) -> list[dict]:
    frames: list[dict] = []
    if not ws.frames_manifest.exists():
        return frames
    for line in ws.frames_manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            record["_abs"] = str((ws.root / record["path"]).resolve())
            frames.append(record)
    frames.sort(key=lambda r: r["frame_id"])
    return frames


def _duration_ms(ws: Workspace, frames: list[dict]) -> float:
    if ws.meta_json.exists():
        meta = json.loads(ws.meta_json.read_text(encoding="utf-8"))
        if meta.get("duration_s"):
            return float(meta["duration_s"]) * 1000.0
    # fallback: last pts + median inter-frame gap
    pts = [f["pts_ms"] for f in frames]
    if len(pts) < 2:
        return pts[-1] + 1000.0 if pts else 0.0
    gaps = sorted(pts[i + 1] - pts[i] for i in range(len(pts) - 1))
    median = gaps[len(gaps) // 2]
    return pts[-1] + median


# -- viewport detection -------------------------------------------------------
def _detect_viewport(ws: Workspace, frames: list[dict], spec: str) -> tuple[tuple[int, int, int, int], str]:
    import cv2

    first = cv2.imread(frames[0]["_abs"])
    if first is None:
        raise V2DError(f"cannot read frame: {frames[0]['_abs']}")
    height, width = first.shape[:2]

    if spec and spec != "auto":
        return _parse_viewport(spec, width, height), "manual"

    sample = _sample(frames, _SAMPLE_CAP)
    scale = _SMALL_W / width
    small_h = max(1, round(height * scale))
    stack = []
    for frame in sample:
        img = cv2.imread(frame["_abs"], cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        stack.append(cv2.resize(img, (_SMALL_W, small_h), interpolation=cv2.INTER_AREA))
    rect_small = _viewport_from_stack(stack) if len(stack) >= 2 else None

    if rect_small is None:
        log.warning("viewport auto-detection failed; using the full frame (check the preview)")
        return (0, 0, width, height), "fallback-fullframe"

    return _scale_and_pad(rect_small, scale, width, height, _PAD_FRAC), "auto"


def _viewport_from_stack(stack: list) -> tuple[int, int, int, int] | None:
    """Per-pixel temporal-variance rectangle from a list of equal-size gray frames."""
    import cv2
    import numpy as np

    arr = np.stack(stack).astype(np.float32)
    std = arr.std(axis=0)
    if float(std.max()) < _MIN_STD:
        return None  # nothing moves -> no detectable viewport

    norm = (std / std.max() * 255.0).astype(np.uint8)
    _, mask = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((_CLOSE_K, _CLOSE_K), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((_OPEN_K, _OPEN_K), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
    if w * h < _MIN_AREA_FRAC * mask.size:
        return None
    return x, y, w, h


def _scale_and_pad(rect, scale, width, height, pad_frac) -> tuple[int, int, int, int]:
    x, y, w, h = (v / scale for v in rect)
    pad_x, pad_y = w * pad_frac, h * pad_frac
    x0 = max(0, int(x - pad_x))
    y0 = max(0, int(y - pad_y))
    x1 = min(width, int(x + w + pad_x))
    y1 = min(height, int(y + h + pad_y))
    return x0, y0, x1 - x0, y1 - y0


def _parse_viewport(spec: str, width: int, height: int) -> tuple[int, int, int, int]:
    try:
        x, y, w, h = (int(p) for p in spec.split(","))
    except ValueError as exc:
        raise V2DError(f"--viewport must be 'x,y,w,h' (got {spec!r})") from exc
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise V2DError(f"--viewport {spec} is outside the {width}x{height} frame")
    return x, y, w, h


def _write_viewport(ws: Workspace, rect, method: str, frames: list[dict]) -> None:
    import cv2

    x, y, w, h = rect
    first = cv2.imread(frames[0]["_abs"])
    fh, fw = first.shape[:2]
    ws.viewport_json.write_text(
        json.dumps({"x": x, "y": y, "w": w, "h": h, "method": method, "frame_size": [fw, fh]}, indent=2),
        encoding="utf-8",
    )
    preview_frame = frames[len(frames) // 2]["_abs"]
    canvas = cv2.imread(preview_frame)
    if canvas is not None:
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 200, 0), 3)
        cv2.imwrite(str(ws.viewport_preview), canvas)


# -- crop + per-frame scoring -------------------------------------------------
def _crop_and_score(ws: Workspace, frames: list[dict], rect, rotate: str = "none") -> list:
    import cv2
    import imagehash
    import numpy as np
    from PIL import Image

    x, y, w, h = rect
    for old in ws.frames_cropped_dir.glob("*.png"):
        old.unlink()

    hashes = []
    checked = False
    for frame in frames:
        crop = Image.open(frame["_abs"]).convert("RGB").crop((x, y, x + w, y + h))
        crop = _apply_rotation(crop, rotate)
        cropped_path = ws.frames_cropped_dir / Path(frame["path"]).name
        crop.save(cropped_path)
        phash = imagehash.phash(crop)
        gray = np.asarray(crop.convert("L"))
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        if rotate == "none" and not checked:
            checked = True
            if _looks_rotated(gray):
                log.warning(
                    "pages look rotated 90° (text seems to run vertically) — "
                    "if so, re-run `pages` with --rotate cw or --rotate ccw"
                )

        frame["cropped_path"] = str(cropped_path.relative_to(ws.root))
        frame["phash"] = str(phash)
        frame["laplacian_var"] = round(laplacian_var, 2)
        hashes.append(phash)
    return hashes


def _apply_rotation(img, rotate: str):
    from PIL import Image

    return {
        "cw": lambda: img.transpose(Image.ROTATE_270),   # PIL ROTATE_* is counter-clockwise
        "ccw": lambda: img.transpose(Image.ROTATE_90),
        "180": lambda: img.transpose(Image.ROTATE_180),
    }.get(rotate, lambda: img)()


def _looks_rotated(gray) -> bool:
    """Heuristic: upright text makes rows vary more than columns; 90°-rotated text
    makes columns vary more. Compares the coefficient of variation of the dark-pixel
    projections. Best-effort — used only to warn, never to auto-rotate."""
    import numpy as np

    g = gray.astype(np.float32)
    dark = g < (g.mean() - 0.5 * g.std())
    rows = dark.sum(axis=1).astype(np.float32)
    cols = dark.sum(axis=0).astype(np.float32)

    def cov(a) -> float:
        m = float(a.mean())
        return float(a.var()) / (m * m) if m > 0 else 0.0

    return cov(cols) > 1.6 * cov(rows) and cov(cols) > 0.05


def _compute_persistence(frames: list[dict], duration_ms: float) -> None:
    for i, frame in enumerate(frames):
        if i + 1 < len(frames):
            persist = frames[i + 1]["pts_ms"] - frame["pts_ms"]
        else:
            persist = max(duration_ms - frame["pts_ms"], 0.0)
        frame["persist_ms"] = round(persist, 3)


# -- runs + classification ----------------------------------------------------
def _group_runs(hashes: list, hamming: int) -> list[list[int]]:
    """Group consecutive frames that stay within `hamming` of the run's anchor.

    Anchored (not pairwise) so a slow drift breaks the run — a genuinely stable
    view forms a run, a scroll does not.
    """
    if not hashes:
        return []
    runs = [[0]]
    anchor = 0
    for i in range(1, len(hashes)):
        if (hashes[i] - hashes[anchor]) <= hamming:
            runs[-1].append(i)
        else:
            runs.append([i])
            anchor = i
    return runs


def _classify(frames: list[dict], runs: list[list[int]], min_page_ms: float) -> list[dict]:
    page_runs = []
    for members in runs:
        duration = sum(frames[i]["persist_ms"] for i in members)
        is_page = duration >= min_page_ms
        for i in members:
            frames[i]["role"] = "page" if is_page else "transition"
        if is_page:
            page_runs.append({
                "frames": members,
                "duration_ms": round(duration, 3),
                "first_pts": frames[members[0]]["pts_ms"],
            })
    return page_runs


def _best_frame(frames: list[dict], members: list[int]) -> int:
    """Sharpest frame in the run; ties broken toward the middle."""
    mid = members[len(members) // 2]
    best = max(
        members,
        key=lambda i: (frames[i]["laplacian_var"], -abs(i - mid)),
    )
    return best


def _revisit_merge(page_runs: list[dict], frames: list[dict], hashes: list, hamming: int) -> list[dict]:
    """Collapse page runs whose best frames look alike (a revisited page)."""
    distinct: list[dict] = []
    for pr in page_runs:
        best_idx = pr["best_idx"]
        rep = hashes[best_idx]
        match = next(
            (d for d in distinct if (rep - hashes[d["best_idx"]]) <= hamming), None
        )
        if match is None:
            distinct.append({
                "best_idx": best_idx,
                "first_pts": pr["first_pts"],
                "members": list(pr["frames"]),
                "cluster_size": len(pr["frames"]),
                "revisit_pts": [],
            })
        else:
            match["members"].extend(pr["frames"])
            match["cluster_size"] += len(pr["frames"])
            match["revisit_pts"].append(pr["first_pts"])
            match["first_pts"] = min(match["first_pts"], pr["first_pts"])
            if frames[best_idx]["laplacian_var"] > frames[match["best_idx"]]["laplacian_var"]:
                match["best_idx"] = best_idx
    return distinct


# -- output -------------------------------------------------------------------
def _emit_pages(ws: Workspace, frames: list[dict], distinct: list[dict]) -> None:
    for old in ws.pages_dir.glob("page_*.png"):
        old.unlink()

    records = []
    for page_no, page in enumerate(distinct, start=1):
        best = frames[page["best_idx"]]
        best["is_best"] = True
        best["page"] = page_no
        dest = ws.page_image(page_no)
        shutil.copyfile(ws.root / best["cropped_path"], dest)
        records.append({
            "page": page_no,
            "source_frame_id": best["frame_id"],
            "pts_ms": best["pts_ms"],
            "image": str(dest.relative_to(ws.root)),
            "cluster_size": page["cluster_size"],
            "revisit_pts_ms": page["revisit_pts"],
            "detail_images": [],
        })
    with ws.pages_manifest.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def _write_frames_manifest(ws: Workspace, frames: list[dict]) -> None:
    with ws.frames_manifest.open("w", encoding="utf-8") as fh:
        for frame in frames:
            record = {
                "frame_id": frame["frame_id"],
                "pts_ms": frame["pts_ms"],
                "path": frame["path"],
                "cropped_path": frame.get("cropped_path"),
                "phash": frame.get("phash"),
                "laplacian_var": frame.get("laplacian_var"),
                "persist_ms": frame.get("persist_ms"),
                "run_id": frame.get("run_id"),
                "role": frame.get("role"),
                "page": frame.get("page"),
                "is_best": frame.get("is_best", False),
            }
            fh.write(json.dumps(record) + "\n")


# -- scroll mode (v2 stitching) ----------------------------------------------
def _run_scroll(ws: Workspace, frames: list[dict]) -> None:
    """Stitch overlapping cropped frames into tall page canvases (one per segment)."""
    import numpy as np
    from PIL import Image

    from video2document import stitching

    color = [Image.open(ws.root / f["cropped_path"]).convert("RGB") for f in frames]
    gray = [np.asarray(im.convert("L")) for im in color]
    segments = stitching.stitch(gray)

    for old in ws.pages_dir.glob("page_*.png"):
        old.unlink()

    records = []
    for page_no, segment in enumerate(segments, start=1):
        canvas = stitching.composite(segment, color)
        dest = ws.page_image(page_no)
        canvas.save(dest)
        first = frames[segment[0].index]
        records.append({
            "page": page_no,
            "source_frame_id": first["frame_id"],
            "pts_ms": first["pts_ms"],
            "image": str(dest.relative_to(ws.root)),
            "stitched_from": len(segment),
            "size": list(canvas.size),
            "detail_images": [],
        })
    with ws.pages_manifest.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    log.info(
        "scroll stitch: %d frames -> %d page(s) (sizes %s) -> %s",
        len(frames), len(records), [r["size"] for r in records], ws.pages_dir,
    )


# -- helpers ------------------------------------------------------------------
def _sample(frames: list[dict], cap: int) -> list[dict]:
    if len(frames) <= cap:
        return frames
    step = (len(frames) - 1) / (cap - 1)
    return [frames[round(i * step)] for i in range(cap)]
