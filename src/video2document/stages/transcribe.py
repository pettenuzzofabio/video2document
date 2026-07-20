"""Stage 3 — transcribe each page image with a vision-capable CLI LLM.

For each ``pages/page_NNNN.png`` (optionally filtered by ``--pages``, skipping those
already done unless ``--force``): call the engine with the page image and a strict
no-guess prompt, parse the sentinel-delimited response into page Markdown + a JSON
sidecar, validate the sidecar, retry once on malformed output, crop any declared
figures into ``assets/`` and rewrite their placeholders in the Markdown. See PLAN.md §3–4.

Per-page failures are isolated: they are logged, the raw output is kept as
``llm/page_NNNN.error.txt``, and the batch continues.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from video2document import engines, prompts
from video2document.exceptions import V2DError
from video2document.workspace import Workspace

log = logging.getLogger(__name__)

_FIGURE_PAD_PCT = 2.0  # expand each figure bbox by this % of page size before cropping


class _ParseError(Exception):
    """The model's response could not be parsed/validated (triggers one retry)."""


def run(
    ws: Workspace,
    *,
    engine: str,
    pages_spec: str | None,
    force: bool,
    model: str | None = None,
    engine_impl: "engines.Engine | None" = None,
) -> None:
    pages_meta = _load_pages(ws)
    if not pages_meta:
        raise V2DError("no pages found — run `v2d pages` first")

    selected = _select(pages_meta, pages_spec)
    if not selected:
        raise V2DError(f"page selection {pages_spec!r} matched no pages")

    eng = engine_impl or engines.get_engine(engine, model)

    done = failed = skipped = 0
    for meta in selected:
        page_no = meta["page"]
        if ws.page_md(page_no).exists() and not force:
            skipped += 1
            continue
        image = (ws.root / meta["image"]).resolve()
        if not image.is_file():
            log.warning("page %d: image missing (%s); skipping", page_no, image)
            failed += 1
            continue
        try:
            _transcribe_one(ws, eng, page_no, image)
            done += 1
            log.info("page %d transcribed", page_no)
        except V2DError as exc:
            failed += 1
            log.warning("page %d failed: %s", page_no, exc)

    log.info(
        "transcribe: %d done, %d skipped, %d failed (engine=%s) -> %s",
        done, skipped, failed, getattr(eng, "name", engine), ws.llm_dir,
    )
    if failed and done == 0 and skipped == 0:
        raise V2DError("all selected pages failed to transcribe (see llm/*.error.txt)")


def _transcribe_one(ws: Workspace, eng, page_no: int, image: Path) -> None:
    prompt = prompts.build_transcription_prompt(page_no)

    raw = eng.transcribe_page(image, prompt)
    try:
        markdown, sidecar = _parse_and_validate(raw)
    except _ParseError:
        raw = eng.transcribe_page(image, prompt)  # one retry
        try:
            markdown, sidecar = _parse_and_validate(raw)
        except _ParseError as exc:
            (ws.llm_dir / f"page_{page_no:04d}.error.txt").write_text(raw, encoding="utf-8")
            raise V2DError(f"malformed model output after retry: {exc}") from exc

    sidecar["page"] = page_no  # enforce the pipeline page number
    markdown = _process_figures(ws, page_no, image, markdown, sidecar)

    ws.page_md(page_no).write_text(markdown.strip() + "\n", encoding="utf-8")
    ws.page_json(page_no).write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")


# -- parsing ------------------------------------------------------------------
def _parse_and_validate(raw: str) -> tuple[str, dict]:
    import jsonschema

    markdown, json_str = _split_sections(raw)
    try:
        sidecar = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise _ParseError(f"sidecar is not valid JSON: {exc}") from exc
    try:
        jsonschema.validate(sidecar, prompts.PAGE_SIDECAR_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise _ParseError(f"sidecar failed schema: {exc.message}") from exc
    return markdown, sidecar


def _split_sections(raw: str) -> tuple[str, str]:
    i = raw.find(prompts.MARKDOWN_SENTINEL)
    j = raw.find(prompts.JSON_SENTINEL)
    if i == -1 or j == -1 or j < i:
        raise _ParseError("missing or misordered sentinels")
    markdown = raw[i + len(prompts.MARKDOWN_SENTINEL) : j].strip()
    json_str = _strip_fences(raw[j + len(prompts.JSON_SENTINEL) :].strip())
    return markdown, json_str


def _strip_fences(text: str) -> str:
    """Defensively remove a ```/```json fence the model may have added."""
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


# -- figures ------------------------------------------------------------------
def _process_figures(ws: Workspace, page_no: int, image: Path, markdown: str, sidecar: dict) -> str:
    figures = sidecar.get("figures") or []
    if not figures:
        return markdown

    from PIL import Image

    page_img = Image.open(image).convert("RGB")
    width, height = page_img.size

    for fig in figures:
        fig_id = fig["id"]
        asset = ws.figure_asset(page_no, fig_id)
        crop = _crop_figure(page_img, fig.get("bbox_pct"), width, height)
        crop.save(asset)
        rel = f"../assets/{asset.name}"
        placeholder = f"]({prompts.FIGURE_PLACEHOLDER_PREFIX}{fig_id})"
        if placeholder in markdown:
            markdown = markdown.replace(placeholder, f"]({rel})")
        else:
            caption = fig.get("caption") or fig_id
            markdown += f"\n\n![{caption}]({rel})\n"
    return markdown


def _crop_figure(page_img, bbox_pct, width: int, height: int):
    """Crop the figure bbox (+padding); fall back to the full page on a bad bbox."""
    if not _valid_bbox(bbox_pct):
        log.warning("figure bbox %r invalid; embedding the full page instead", bbox_pct)
        return page_img
    x1, y1, x2, y2 = bbox_pct
    px1 = max(0, int((x1 - _FIGURE_PAD_PCT) / 100.0 * width))
    py1 = max(0, int((y1 - _FIGURE_PAD_PCT) / 100.0 * height))
    px2 = min(width, int((x2 + _FIGURE_PAD_PCT) / 100.0 * width))
    py2 = min(height, int((y2 + _FIGURE_PAD_PCT) / 100.0 * height))
    if px2 <= px1 or py2 <= py1:
        return page_img
    return page_img.crop((px1, py1, px2, py2))


def _valid_bbox(bbox_pct) -> bool:
    if not isinstance(bbox_pct, (list, tuple)) or len(bbox_pct) != 4:
        return False
    x1, y1, x2, y2 = bbox_pct
    if not all(isinstance(v, (int, float)) for v in bbox_pct):
        return False
    if not (0 <= x1 < x2 <= 100 and 0 <= y1 < y2 <= 100):
        return False
    return (x2 - x1) * (y2 - y1) >= 1.0  # at least ~1% area


# -- loading / selection ------------------------------------------------------
def _load_pages(ws: Workspace) -> list[dict]:
    if not ws.pages_manifest.exists():
        return []
    pages = [
        json.loads(line)
        for line in ws.pages_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    pages.sort(key=lambda p: p["page"])
    return pages


def _select(pages_meta: list[dict], spec: str | None) -> list[dict]:
    if not spec:
        return pages_meta
    wanted = _parse_page_spec(spec)
    return [p for p in pages_meta if p["page"] in wanted]


def _parse_page_spec(spec: str) -> set[int]:
    wanted: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            wanted.update(range(int(lo), int(hi) + 1))
        else:
            wanted.add(int(part))
    return wanted
