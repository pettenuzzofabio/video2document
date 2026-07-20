"""Stage — incorporate supplied high-resolution diagram photos (PLAN.md v2).

Dense diagrams that are illegible in the video can be supplied separately as hi-res
photos (dropped into ``<workdir>/details/``). This stage matches each photo to the page
it belongs to (ORB feature matching + homography — no LLM), embeds the hi-res image on
that page, and runs one LLM pass on it to extract the diagram's data into the page's
Markdown. Only pages with a confident match are touched (no over-engineering).

Run it after ``transcribe`` and before ``assemble``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from video2document import engines, prompts
from video2document.exceptions import V2DError
from video2document.workspace import Workspace

log = logging.getLogger(__name__)

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_ORB_WIDTH = 1000   # downscale width for feature matching (speed / scale consistency)
_RATIO = 0.75       # Lowe ratio-test threshold


def run(
    ws: Workspace,
    *,
    details_dir: str | None = None,
    engine: str = "claude",
    model: str | None = None,
    min_matches: int = 15,
    engine_impl: "engines.Engine | None" = None,
) -> None:
    source = Path(details_dir).expanduser() if details_dir else (ws.root / "details")
    if not source.is_dir():
        raise V2DError(f"details folder not found: {source} (put hi-res diagram photos there)")
    photos = sorted(p for p in source.iterdir() if p.suffix.lower() in _IMG_EXTS)
    if not photos:
        raise V2DError(f"no images found in {source}")

    records = _load_pages(ws)
    if not records:
        raise V2DError("no pages found — run `v2d pages` (and `transcribe`) first")

    import cv2

    orb = cv2.ORB_create(nfeatures=3000)
    page_feats = []
    for rec in records:
        gray = _load_gray(ws.root / rec["image"])
        kp, des = orb.detectAndCompute(gray, None) if gray is not None else (None, None)
        page_feats.append((rec["page"], kp, des))

    eng = engine_impl or engines.get_engine(engine, model)
    per_page_count: dict[int, int] = {}
    matched = unmatched = 0
    for photo in photos:
        gray = _load_gray(photo)
        if gray is None:
            log.warning("could not read %s; skipping", photo.name)
            continue
        result = _match(orb, gray, page_feats, min_matches)
        if result is None:
            unmatched += 1
            log.warning("detail %s: no confident page match (< %d inliers)", photo.name, min_matches)
            continue
        page_no, inliers = result
        matched += 1
        per_page_count[page_no] = per_page_count.get(page_no, 0) + 1
        _attach(ws, eng, records, page_no, per_page_count[page_no], photo)
        log.info("detail %s -> page %d (%d inliers)", photo.name, page_no, inliers)

    _write_pages(ws, records)
    log.info("details: %d matched, %d unmatched", matched, unmatched)
    if matched == 0:
        raise V2DError(
            "no detail photo matched a page confidently — try a lower --min-matches, "
            "or check the photos are of diagrams that appear in the video"
        )


def _attach(ws: Workspace, eng, records: list[dict], page_no: int, k: int, photo: Path) -> None:
    from PIL import Image

    asset = ws.figure_asset(page_no, f"detail{k}")
    Image.open(photo).convert("RGB").save(asset)

    detail_md = eng.transcribe_page(asset, prompts.DETAIL_EXTRACTION_PROMPT).strip()

    md_path = ws.page_md(page_no)
    if md_path.exists():
        body = md_path.read_text(encoding="utf-8").rstrip()
    else:
        body = f"# Page {page_no}"
        log.warning("page %d has no transcription yet; creating a stub", page_no)
    rel = f"../assets/{asset.name}"
    md_path.write_text(
        f"{body}\n\n### Diagram detail (high-resolution)\n\n![{photo.stem}]({rel})\n\n{detail_md}\n",
        encoding="utf-8",
    )
    for rec in records:
        if rec["page"] == page_no:
            rec.setdefault("detail_images", []).append(str(asset.relative_to(ws.root)))


def _match(orb, photo_gray, page_feats, min_inliers: int):
    """Return (page_no, inliers) for the best-matching page, or None if unconfident."""
    import cv2
    import numpy as np

    kp_p, des_p = orb.detectAndCompute(photo_gray, None)
    if des_p is None or len(des_p) < 2:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    best_page, best_inliers = None, 0
    for page_no, kp_g, des_g in page_feats:
        if des_g is None or len(des_g) < 2:
            continue
        good = [
            pair[0]
            for pair in matcher.knnMatch(des_p, des_g, k=2)
            if len(pair) == 2 and pair[0].distance < _RATIO * pair[1].distance
        ]
        if len(good) < min_inliers:
            continue
        src = np.float32([kp_p[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp_g[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        inliers = int(mask.sum()) if mask is not None else 0
        if inliers > best_inliers:
            best_page, best_inliers = page_no, inliers
    return (best_page, best_inliers) if best_inliers >= min_inliers else None


def _load_gray(path: Path):
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > _ORB_WIDTH:
        scale = _ORB_WIDTH / w
        img = cv2.resize(img, (_ORB_WIDTH, round(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _load_pages(ws: Workspace) -> list[dict]:
    if not ws.pages_manifest.exists():
        return []
    return [
        json.loads(line)
        for line in ws.pages_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_pages(ws: Workspace, records: list[dict]) -> None:
    with ws.pages_manifest.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
