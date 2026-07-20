#!/usr/bin/env python3
"""Generate synthetic "scrolling document" fixture videos for testing.

These are deterministic, dependency-light stand-ins so the pipeline and its tests
have something to run against without a manual screen-capture step. They are NOT a
substitute for real recordings (see fixtures/README.md).

Each fixture is a short MP4 of a fake document viewer (static toolbar + sidebar,
i.e. "chrome") paging through a few pages, plus a ground-truth JSON describing the
distinct pages, their authored text, and the viewing order.

Pure-Python: Pillow renders the pages; the ffmpeg binary bundled with imageio-ffmpeg
encodes the frames. No system ffmpeg, no PDF tooling, no network.

Usage:
    uv run python scripts/make_fixtures.py [--only NAME] [--fps N] [--dump-sample]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# -- geometry (all dimensions even, for yuv420p) -----------------------------
CANVAS_W, CANVAS_H = 1280, 800
TOOLBAR_H = 48
SIDEBAR_W = 140
VP_X, VP_Y = SIDEBAR_W, TOOLBAR_H
VP_W, VP_H = CANVAS_W - SIDEBAR_W, CANVAS_H - TOOLBAR_H
PAGE_W, PAGE_H = 560, 720
PAGE_MARGIN_Y = (VP_H - PAGE_H) // 2
PAGE_X = (VP_W - PAGE_W) // 2
GAP = 32  # gray gap between pages while scrolling

# -- colours -----------------------------------------------------------------
C_TOOLBAR = (58, 61, 64)
C_SIDEBAR = (88, 91, 95)
C_VIEWPORT = (128, 131, 135)
C_PAGE = (255, 255, 255)
C_BORDER = (206, 208, 210)
C_INK = (32, 32, 34)
C_MUTED = (96, 98, 102)
C_BAR = (66, 118, 186)
C_AXIS = (70, 72, 76)
C_CURSOR_FILL = (250, 250, 250)
C_CURSOR_EDGE = (20, 20, 20)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]
_FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    # Fallback: Pillow's built-in font, scaled (Pillow >= 10.1).
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        line = ""
        for word in words:
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


# -- page rendering ----------------------------------------------------------
def _blank_page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    page = Image.new("RGB", (PAGE_W, PAGE_H), C_PAGE)
    draw = ImageDraw.Draw(page)
    draw.rectangle([0, 0, PAGE_W - 1, PAGE_H - 1], outline=C_BORDER, width=1)
    return page, draw


def _render_text(spec: dict) -> Image.Image:
    page, draw = _blank_page()
    title_font = _load_font(30, bold=True)
    body_font = _load_font(20)
    pad = 40
    y = pad
    draw.text((pad, y), spec["title"], font=title_font, fill=C_INK)
    y += 52
    for para in spec["body"]:
        for line in _wrap(draw, para, body_font, PAGE_W - 2 * pad):
            draw.text((pad, y), line, font=body_font, fill=C_INK)
            y += 30
        y += 14
    return page


def _render_table(spec: dict) -> Image.Image:
    page, draw = _blank_page()
    title_font = _load_font(28, bold=True)
    head_font = _load_font(19, bold=True)
    cell_font = _load_font(19)
    pad = 40
    draw.text((pad, pad), spec["title"], font=title_font, fill=C_INK)

    columns = spec["columns"]
    rows = spec["rows"]
    top = pad + 70
    row_h = 44
    table_w = PAGE_W - 2 * pad
    col_w = table_w // len(columns)
    n_rows = len(rows) + 1

    # grid
    for i in range(n_rows + 1):
        yy = top + i * row_h
        draw.line([pad, yy, pad + col_w * len(columns), yy], fill=C_AXIS, width=1)
    for j in range(len(columns) + 1):
        xx = pad + j * col_w
        draw.line([xx, top, xx, top + row_h * n_rows], fill=C_AXIS, width=1)

    # header
    for j, name in enumerate(columns):
        draw.text((pad + j * col_w + 10, top + 11), name, font=head_font, fill=C_INK)
    # body
    for i, row in enumerate(rows, start=1):
        for j, value in enumerate(row):
            draw.text(
                (pad + j * col_w + 10, top + i * row_h + 11),
                str(value),
                font=cell_font,
                fill=C_INK,
            )
    return page


def _render_chart(spec: dict) -> Image.Image:
    page, draw = _blank_page()
    title_font = _load_font(28, bold=True)
    label_font = _load_font(18)
    caption_font = _load_font(17)
    pad = 40
    draw.text((pad, pad), spec["title"], font=title_font, fill=C_INK)

    labels = spec["labels"]
    values = spec["values"]
    plot_left, plot_right = pad + 20, PAGE_W - pad
    plot_bottom, plot_top = 470, 150
    draw.line([plot_left, plot_top, plot_left, plot_bottom], fill=C_AXIS, width=2)
    draw.line([plot_left, plot_bottom, plot_right, plot_bottom], fill=C_AXIS, width=2)

    n = len(values)
    span = plot_right - plot_left
    slot = span / n
    bar_w = slot * 0.55
    vmax = max(values) or 1
    for i, (label, value) in enumerate(zip(labels, values)):
        cx = plot_left + slot * (i + 0.5)
        h = (value / vmax) * (plot_bottom - plot_top - 20)
        x0, x1 = cx - bar_w / 2, cx + bar_w / 2
        draw.rectangle([x0, plot_bottom - h, x1, plot_bottom], fill=C_BAR)
        draw.text((cx - 12, plot_bottom - h - 24), str(value), font=label_font, fill=C_INK)
        draw.text((cx - 24, plot_bottom + 8), label, font=label_font, fill=C_MUTED)

    for line in _wrap(draw, spec["caption"], caption_font, PAGE_W - 2 * pad):
        draw.text((pad, plot_bottom + 60), line, font=caption_font, fill=C_MUTED)
    return page


_RENDERERS = {"text": _render_text, "table": _render_table, "chart": _render_chart}


def _page_text(spec: dict) -> str:
    """Exact ground-truth text for a page spec."""
    if spec["type"] == "text":
        return spec["title"] + "\n\n" + "\n\n".join(spec["body"])
    if spec["type"] == "table":
        header = " | ".join(spec["columns"])
        body = "\n".join(" | ".join(str(c) for c in row) for row in spec["rows"])
        return f"{spec['title']}\n{header}\n{body}"
    if spec["type"] == "chart":
        data = "\n".join(f"{lbl}: {val}" for lbl, val in zip(spec["labels"], spec["values"]))
        return f"{spec['title']}\n{data}\n{spec['caption']}"
    raise ValueError(spec["type"])


# -- compositing -------------------------------------------------------------
def _cursor(draw: ImageDraw.ImageDraw) -> None:
    x, y = CANVAS_W - 70, CANVAS_H - 70  # parked in the right gray margin
    arrow = [(x, y), (x, y + 26), (x + 7, y + 19), (x + 12, y + 30), (x + 17, y + 28),
             (x + 12, y + 17), (x + 20, y + 17)]
    draw.polygon(arrow, fill=C_CURSOR_FILL, outline=C_CURSOR_EDGE)


def _chrome(viewport: Image.Image) -> Image.Image:
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), C_VIEWPORT)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, CANVAS_W, TOOLBAR_H], fill=C_TOOLBAR)
    draw.rectangle([0, TOOLBAR_H, SIDEBAR_W, CANVAS_H], fill=C_SIDEBAR)
    canvas.paste(viewport, (VP_X, VP_Y))
    _cursor(draw)
    return canvas


def _viewport_single(page: Image.Image) -> Image.Image:
    vp = Image.new("RGB", (VP_W, VP_H), C_VIEWPORT)
    vp.paste(page, (PAGE_X, PAGE_MARGIN_Y))
    return vp


def _viewport_window(page_a: Image.Image, page_b: Image.Image, y_win: int) -> Image.Image:
    """A viewport-height window of the A-over-B scroll strip."""
    strip_h = PAGE_MARGIN_Y + PAGE_H + GAP + PAGE_H + PAGE_MARGIN_Y
    strip = Image.new("RGB", (VP_W, strip_h), C_VIEWPORT)
    strip.paste(page_a, (PAGE_X, PAGE_MARGIN_Y))
    strip.paste(page_b, (PAGE_X, PAGE_MARGIN_Y + PAGE_H + GAP))
    return strip.crop((0, y_win, VP_W, y_win + VP_H))


def _build_frames(pages: list[Image.Image], order: list[int], dwell: int, trans: int) -> list[Image.Image]:
    frames: list[Image.Image] = []
    scroll = PAGE_H + GAP
    for i, page_idx in enumerate(order):
        page = pages[page_idx]
        frames.extend(_chrome(_viewport_single(page)) for _ in range(dwell))
        if i + 1 < len(order):
            nxt = pages[order[i + 1]]
            for t in range(1, trans + 1):
                y = round(scroll * t / (trans + 1))
                frames.append(_chrome(_viewport_window(page, nxt, y)))
    return frames


# -- encoding ----------------------------------------------------------------
def _encode(frames: list[Image.Image], out: Path, fps: int) -> None:
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for i, frame in enumerate(frames):
            frame.save(tmpdir / f"{i:06d}.png")
        cmd = [
            ffmpeg, "-y", "-framerate", str(fps),
            "-i", str(tmpdir / "%06d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-movflags", "+faststart", str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg failed:\n" + proc.stderr[-2000:])


# -- fixture definitions -----------------------------------------------------
def _fixtures() -> dict[str, dict]:
    en = "en"
    it = "it"
    return {
        "en_simple": {
            "fps": 6,
            "order": [0, 1, 2],
            "pages": [
                {"language": en, "type": "text", "title": "Chapter 1 — Introduction",
                 "body": [
                     "This document is a synthetic fixture produced for testing the "
                     "video2document pipeline. It contains ordinary running text so "
                     "the transcription stage has something faithful to reconstruct.",
                     "Each page carries a distinct heading and several sentences. The "
                     "wording is plain on purpose, to make character-level accuracy "
                     "checks easy to reason about.",
                 ]},
                {"language": en, "type": "text", "title": "Chapter 2 — Methods",
                 "body": [
                     "The pipeline extracts frames, isolates one clean image per page, "
                     "and transcribes each page with a vision language model.",
                     "This page exists to verify that page boundaries are detected and "
                     "that reading order across pages is preserved end to end.",
                 ]},
                {"language": en, "type": "text", "title": "Chapter 3 — Results",
                 "body": [
                     "If reconstruction works, this third page appears last and in full, "
                     "with its heading intact and no text lost at the page break.",
                     "That is the entire success criterion for the simplest fixture.",
                 ]},
            ],
        },
        "it_table_chart": {
            "fps": 6,
            "order": [0, 1, 2],
            "pages": [
                {"language": it, "type": "text", "title": "Relazione Trimestrale",
                 "body": [
                     "Questo documento è una fixture sintetica in italiano, con accenti "
                     "e testo corrente, per verificare la fedeltà della trascrizione.",
                     "Le pagine successive contengono una tabella e un grafico, così da "
                     "esercitare la conservazione di tabelle e figure.",
                 ]},
                {"language": it, "type": "table", "title": "Tabella 1 — Vendite",
                 "columns": ["Mese", "Unità", "Ricavi"],
                 "rows": [["Gennaio", "120", "3.600"],
                          ["Febbraio", "150", "4.500"],
                          ["Marzo", "180", "5.400"]]},
                {"language": it, "type": "chart", "title": "Grafico 1 — Andamento",
                 "labels": ["Gen", "Feb", "Mar"], "values": [120, 150, 180],
                 "caption": "Le vendite crescono ogni mese nel primo trimestre."},
            ],
        },
        "en_backscroll": {
            "fps": 6,
            "order": [0, 1, 2, 1, 0],  # scrolls forward then back — tests revisit merge
            "pages": [
                {"language": "en", "type": "text", "title": "Section A — Overview",
                 "body": ["The reader scrolls forward to Section C, then scrolls back "
                          "through B to A. Only three distinct pages exist."]},
                {"language": "en", "type": "text", "title": "Section B — Detail",
                 "body": ["A page that is viewed twice must still be emitted once. "
                          "The revisit merge in the pages stage is what guarantees it."]},
                {"language": "en", "type": "text", "title": "Section C — Summary",
                 "body": ["After this page the viewport scrolls back upward, revisiting "
                          "pages already seen."]},
            ],
        },
    }


def _generate(name: str, spec: dict, out_dir: Path, fps: int, dwell: int, trans: int,
              dump_sample: bool) -> None:
    pages = [_RENDERERS[p["type"]](p) for p in spec["pages"]]
    frames = _build_frames(pages, spec["order"], dwell, trans)
    video = out_dir / f"{name}.mp4"
    _encode(frames, video, fps)

    order = spec["order"]
    ground_truth = {
        "name": name,
        "fps": fps,
        "canvas": [CANVAS_W, CANVAS_H],
        "viewport": [VP_X, VP_Y, VP_W, VP_H],
        "view_order": order,
        "distinct_pages": len(spec["pages"]),
        "first_appearance_order": sorted(set(order), key=order.index),
        "pages": [
            {"index": i, "language": p["language"], "type": p["type"], "text": _page_text(p)}
            for i, p in enumerate(spec["pages"])
        ],
    }
    (out_dir / f"{name}.pages.json").write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if dump_sample:
        frames[dwell // 2].save(out_dir / f"{name}.sample_page.png")
        if len(frames) > dwell:
            frames[dwell].save(out_dir / f"{name}.sample_transition.png")
    print(f"  {name}: {len(frames)} frames -> {video.name} + {name}.pages.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_out = Path(__file__).resolve().parents[1] / "fixtures" / "generated"
    parser.add_argument("--out", type=Path, default=default_out, help="Output directory.")
    parser.add_argument("--only", help="Generate only this fixture by name.")
    parser.add_argument("--fps", type=int, default=6, help="Video frame rate.")
    parser.add_argument("--dwell", type=int, default=8, help="Frames a page stays fully visible.")
    parser.add_argument("--trans", type=int, default=3, help="Scroll frames between pages.")
    parser.add_argument("--dump-sample", action="store_true", help="Also write sample frame PNGs.")
    args = parser.parse_args()

    fixtures = _fixtures()
    if args.only:
        if args.only not in fixtures:
            parser.error(f"unknown fixture {args.only!r}; choices: {', '.join(fixtures)}")
        fixtures = {args.only: fixtures[args.only]}

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"Generating {len(fixtures)} fixture(s) into {args.out}")
    for name, spec in fixtures.items():
        _generate(name, spec, args.out, args.fps, args.dwell, args.trans, args.dump_sample)


if __name__ == "__main__":
    main()
