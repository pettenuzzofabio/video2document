"""Stage 4 — merge per-page transcriptions into the final document.

Produces ``out/reconstructed.md`` (canonical) and ``out/report.md`` (a QA summary),
plus ``out/reconstructed.pdf`` with ``--pdf``. Steps (PLAN.md §3):

* **Header/footer**: the model already routed running headers/footers/page numbers
  into the sidecar (out of the body). Here we *verify* them by digit-insensitive
  repetition across pages: values that recur on >= 60% of pages are confirmed running
  (stay suppressed); one-off values were probably a misclassified heading, so they are
  re-inserted into the body to avoid losing content.
* **Boundary healing**: where page N ends and page N+1 begins mid-paragraph/-table
  (their ``continues_*`` flags agree), the split block is joined — deterministically,
  and optionally refined by a small LLM merge on just the boundary text (``--merge-pass``).
* **Report**: per-page confidence, unclear spans, figures, healed boundaries, suppressed
  headers/footers, and any pages missing a transcription.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime

from video2document import engines
from video2document.exceptions import V2DError
from video2document.workspace import Workspace

log = logging.getLogger(__name__)

_MERGE_PROMPT = """\
The two Markdown fragments below are the END of one page and the START of the next \
page of the same document. They are a single paragraph, sentence, list, or table split \
across a page break. Join them into ONE continuous, correct Markdown fragment (fix a \
broken/hyphenated word, merge the sentence, or concatenate table rows). Do not add, \
remove, translate, or summarize anything. Output ONLY the merged Markdown, nothing else.

--- END OF PAGE ---
{a}
--- START OF NEXT PAGE ---
{b}
"""


def run(
    ws: Workspace,
    *,
    pdf: bool,
    merge_pass: bool,
    engine: str = "claude",
    model: str | None = None,
    engine_impl: "engines.Engine | None" = None,
) -> None:
    pages = _load(ws)
    if not pages:
        raise V2DError("no pages found — run `v2d pages` first")
    if all(p.get("_missing") for p in pages):
        raise V2DError("no transcribed pages found — run `v2d transcribe` first")

    suppressed, reinserted = _apply_header_footer(pages)

    boundaries = _boundaries(pages)
    merger = _make_merger(merge_pass, boundaries, engine, model, engine_impl)
    document, healed = _assemble(pages, merger)

    ws.reconstructed_md.write_text(document, encoding="utf-8")
    _write_report(ws, pages, healed, suppressed, reinserted)

    log.info(
        "assembled %d pages -> %s (%d boundaries healed, %d headers/footers suppressed)",
        sum(1 for p in pages if not p.get("_missing")),
        ws.reconstructed_md, len(healed), len(suppressed),
    )
    if pdf:
        _render_pdf(ws)
        log.info("rendered %s", ws.reconstructed_pdf)


# -- loading ------------------------------------------------------------------
def _load(ws: Workspace) -> list[dict]:
    if not ws.pages_manifest.exists():
        return []
    pages: list[dict] = []
    for line in ws.pages_manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        page_no = rec["page"]
        md_path = ws.page_md(page_no)
        if md_path.exists():
            sidecar_path = ws.page_json(page_no)
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.exists() else {}
            pages.append({"page": page_no, "md": md_path.read_text(encoding="utf-8"), "sidecar": sidecar})
        else:
            pages.append({"page": page_no, "_missing": True, "sidecar": {}})
    pages.sort(key=lambda p: p["page"])
    return pages


# -- header / footer ----------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text).strip().casefold()


def _apply_header_footer(pages: list[dict]) -> tuple[list, list]:
    transcribed = [p for p in pages if not p.get("_missing")]
    n = len(transcribed)
    header_counts: Counter[str] = Counter()
    footer_counts: Counter[str] = Counter()
    for p in transcribed:
        if p["sidecar"].get("header"):
            header_counts[_norm(p["sidecar"]["header"])] += 1
        if p["sidecar"].get("footer"):
            footer_counts[_norm(p["sidecar"]["footer"])] += 1

    threshold = max(2, math.ceil(0.6 * n))
    suppressed, reinserted = [], []
    for p in transcribed:
        header = p["sidecar"].get("header")
        footer = p["sidecar"].get("footer")
        if header:
            if header_counts[_norm(header)] >= threshold:
                suppressed.append(("header", p["page"], header))
            else:
                p["md"] = f"{header.strip()}\n\n{p['md']}"
                reinserted.append(("header", p["page"], header))
        if footer:
            if footer_counts[_norm(footer)] >= threshold:
                suppressed.append(("footer", p["page"], footer))
            else:
                p["md"] = f"{p['md'].rstrip()}\n\n{footer.strip()}"
                reinserted.append(("footer", p["page"], footer))
    return suppressed, reinserted


# -- assembly + boundary healing ---------------------------------------------
def _boundaries(pages: list[dict]) -> list[tuple[int, int]]:
    out = []
    for prev, cur in zip(pages, pages[1:]):
        if (
            not prev.get("_missing") and not cur.get("_missing")
            and prev["sidecar"].get("continues_to_next")
            and cur["sidecar"].get("continues_from_prev")
        ):
            out.append((prev["page"], cur["page"]))
    return out


def _assemble(pages: list[dict], merger) -> tuple[str, list]:
    blocks: list[str] = []
    healed: list[tuple[int, int]] = []
    prev = None
    for page in pages:
        if page.get("_missing"):
            page_blocks = [f"> _[page {page['page']} was not transcribed]_"]
        else:
            page_blocks = _split_blocks(page["md"])

        can_heal = (
            prev is not None and not prev.get("_missing") and not page.get("_missing")
            and prev["sidecar"].get("continues_to_next")
            and page["sidecar"].get("continues_from_prev")
            and blocks and page_blocks
        )
        if can_heal:
            tail = blocks.pop()
            head = page_blocks[0]
            blocks.append(merger(tail, head))
            blocks.extend(page_blocks[1:])
            healed.append((prev["page"], page["page"]))
        else:
            blocks.extend(page_blocks)
        prev = page

    document = "\n\n".join(b.strip() for b in blocks if b.strip())
    return document + "\n", healed


def _split_blocks(md: str) -> list[str]:
    return [b for b in re.split(r"\n\s*\n", md.strip()) if b.strip()]


def _heal_deterministic(tail: str, head: str) -> str:
    tail_lines = tail.rstrip().splitlines()
    head_lines = head.lstrip().splitlines()
    if (
        tail_lines and head_lines
        and tail_lines[-1].lstrip().startswith("|")
        and head_lines[0].lstrip().startswith("|")
    ):
        # table continuation: drop a repeated header row + its |---| separator
        if len(head_lines) >= 2 and set(head_lines[1].replace("|", "").replace(" ", "")) <= set("-:"):
            head_lines = head_lines[2:]
        return "\n".join(tail_lines + head_lines)
    # paragraph continuation
    tail_text = tail.rstrip()
    head_text = head.lstrip()
    if tail_text.endswith("-"):
        return tail_text[:-1] + head_text  # de-hyphenate
    return f"{tail_text} {head_text}"


def _make_merger(merge_pass: bool, boundaries: list, engine: str, model, engine_impl):
    if not merge_pass or not boundaries:
        return _heal_deterministic

    state = {"engine": engine_impl, "disabled": False}

    def merger(tail: str, head: str) -> str:
        deterministic = _heal_deterministic(tail, head)
        if state["disabled"]:
            return deterministic
        try:
            if state["engine"] is None:
                state["engine"] = engines.get_engine(engine, model)
            merged = state["engine"].complete(_MERGE_PROMPT.format(a=tail, b=head)).strip()
            return merged or deterministic
        except V2DError as exc:
            log.warning("LLM merge unavailable (%s); using deterministic healing", exc)
            state["disabled"] = True
            return deterministic

    return merger


# -- report -------------------------------------------------------------------
def _write_report(ws: Workspace, pages, healed, suppressed, reinserted) -> None:
    transcribed = [p for p in pages if not p.get("_missing")]
    missing = [p for p in pages if p.get("_missing")]
    lines = [
        "# Reconstruction report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Pages: {len(pages)} (transcribed: {len(transcribed)}, missing: {len(missing)})",
        f"- Boundaries healed: {len(healed)}",
        "",
        "## Per page",
        "",
        "| Page | Lang | Confidence | Figures | Unclear | Continues |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for p in pages:
        if p.get("_missing"):
            lines.append(f"| {p['page']} | — | **missing** | — | — | — |")
            continue
        s = p["sidecar"]
        cont = ("←" if s.get("continues_from_prev") else "") + ("→" if s.get("continues_to_next") else "") or "—"
        lines.append(
            f"| {p['page']} | {s.get('language', '?')} | {s.get('confidence', '?')} "
            f"| {len(s.get('figures') or [])} | {len(s.get('unclear') or [])} | {cont} |"
        )

    unclear = [(p["page"], u) for p in transcribed for u in (p["sidecar"].get("unclear") or [])]
    lines += ["", f"## Unclear spans ({len(unclear)})", ""]
    lines += [f"- p{pg}: {note}" for pg, note in unclear] or ["- none"]

    figures = [
        (p["page"], f.get("id"), f.get("kind"), f.get("caption"))
        for p in transcribed for f in (p["sidecar"].get("figures") or [])
    ]
    lines += ["", f"## Figures ({len(figures)})", ""]
    lines += [f"- p{pg} {fid} ({kind}): {cap}" for pg, fid, kind, cap in figures] or ["- none"]

    lines += ["", f"## Boundaries healed ({len(healed)})", ""]
    lines += [f"- pages {a}→{b}" for a, b in healed] or ["- none"]

    lines += ["", f"## Suppressed running header/footer ({len(suppressed)})", ""]
    lines += [f"- {kind} (p{pg}): {text}" for kind, pg, text in suppressed] or ["- none"]

    if reinserted:
        lines += ["", f"## Re-inserted (one-off, likely a heading) ({len(reinserted)})", ""]
        lines += [f"- {kind} (p{pg}): {text}" for kind, pg, text in reinserted]

    if missing:
        lines += ["", "## Missing transcriptions", ""]
        lines += [f"- page {p['page']} (no `llm/page_{p['page']:04d}.md`)" for p in missing]

    ws.report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- pdf ----------------------------------------------------------------------
_PDF_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 1.8cm; }}
body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.4; }}
h1 {{ font-size: 18pt; }} h2 {{ font-size: 14pt; }} h3 {{ font-size: 12pt; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #888888; padding: 4px 6px; text-align: left; }}
img {{ max-width: 100%; }}
code, pre {{ font-family: Courier, monospace; font-size: 9pt; }}
</style></head><body>{body}</body></html>"""


def _render_pdf(ws: Workspace) -> None:
    """Render reconstructed.md to PDF: pandoc if available (best), else pure-pip fallback."""
    if _render_pdf_pandoc(ws):
        log.info("PDF rendered via pandoc")
        return
    _render_pdf_python(ws)
    log.info("PDF rendered via xhtml2pdf")


def _render_pdf_pandoc(ws: Workspace) -> bool:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return False
    proc = subprocess.run(
        [pandoc, ws.reconstructed_md.name, "-o", ws.reconstructed_pdf.name, "--standalone"],
        cwd=ws.out_dir, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return True
    log.warning("pandoc failed (%s); falling back to xhtml2pdf", proc.stderr[-200:].strip())
    return False


def _render_pdf_python(ws: Workspace) -> None:
    try:
        import markdown as md_lib
        from xhtml2pdf import pisa
    except ImportError as exc:  # pragma: no cover
        raise V2DError(
            "PDF rendering needs `markdown` + `xhtml2pdf` (run `uv sync`), or install pandoc"
        ) from exc

    html_body = md_lib.markdown(
        ws.reconstructed_md.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    html = _PDF_HTML.format(body=html_body)

    def resolve(uri: str, _rel: str) -> str:
        if uri.startswith(("http://", "https://", "data:")):
            return uri
        return str((ws.out_dir / uri).resolve())  # ../assets/... relative to out/

    with ws.reconstructed_pdf.open("wb") as fh:
        result = pisa.CreatePDF(html, dest=fh, link_callback=resolve, encoding="utf-8")
    if result.err:
        raise V2DError("xhtml2pdf could not render the PDF from reconstructed.md")
