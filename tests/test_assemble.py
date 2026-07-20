"""Tests for stage 4 (assemble): concatenation, boundary healing, headers, report."""

from __future__ import annotations

import json
from pathlib import Path

from video2document.stages import assemble
from video2document.workspace import Workspace


def _sc(page: int, **kw) -> dict:
    base = {
        "page": page, "language": "en", "confidence": "high", "figures": [],
        "header": None, "footer": None, "page_number": None, "unclear": [],
        "continues_from_prev": False, "continues_to_next": False,
    }
    base.update(kw)
    return base


def _setup(ws: Workspace, pages: list[dict]) -> None:
    ws.ensure()
    records = []
    for p in pages:
        n = p["page"]
        records.append({
            "page": n, "source_frame_id": 0, "pts_ms": 0.0,
            "image": f"pages/page_{n:04d}.png", "cluster_size": 1,
            "revisit_pts_ms": [], "detail_images": [],
        })
        if "md" in p:
            ws.page_md(n).write_text(p["md"], encoding="utf-8")
            ws.page_json(n).write_text(json.dumps(p.get("sidecar", _sc(n))), encoding="utf-8")
    with ws.pages_manifest.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_concatenates_in_order(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws, [
        {"page": 1, "md": "# One\n\nAlpha.", "sidecar": _sc(1)},
        {"page": 2, "md": "# Two\n\nBeta.", "sidecar": _sc(2)},
    ])
    assemble.run(ws, pdf=False, merge_pass=False)
    doc = ws.reconstructed_md.read_text(encoding="utf-8")
    assert doc.index("# One") < doc.index("# Two")
    assert "Alpha." in doc and "Beta." in doc


def test_boundary_healing_paragraph(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws, [
        {"page": 1, "md": "# One\n\nThe quick brown", "sidecar": _sc(1, continues_to_next=True)},
        {"page": 2, "md": "fox jumps.", "sidecar": _sc(2, continues_from_prev=True)},
    ])
    assemble.run(ws, pdf=False, merge_pass=False)
    assert "The quick brown fox jumps." in ws.reconstructed_md.read_text(encoding="utf-8")


def test_boundary_healing_table_drops_repeated_header(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws, [
        {"page": 1, "md": "| A | B |\n| --- | --- |\n| 1 | 2 |", "sidecar": _sc(1, continues_to_next=True)},
        {"page": 2, "md": "| A | B |\n| --- | --- |\n| 3 | 4 |", "sidecar": _sc(2, continues_from_prev=True)},
    ])
    assemble.run(ws, pdf=False, merge_pass=False)
    doc = ws.reconstructed_md.read_text(encoding="utf-8")
    assert doc.count("| A | B |") == 1
    assert "| 1 | 2 |" in doc and "| 3 | 4 |" in doc


def test_header_footer_suppressed_and_reinserted(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws, [
        {"page": 1, "md": "Body 1", "sidecar": _sc(1, footer="Pagina 1 di 3")},
        {"page": 2, "md": "Body 2", "sidecar": _sc(2, footer="Pagina 2 di 3", header="Sezione B")},
        {"page": 3, "md": "Body 3", "sidecar": _sc(3, footer="Pagina 3 di 3")},
    ])
    assemble.run(ws, pdf=False, merge_pass=False)
    doc = ws.reconstructed_md.read_text(encoding="utf-8")
    assert "Pagina 1 di 3" not in doc        # running footer stays suppressed
    assert "Sezione B" in doc                # one-off header re-inserted (likely a heading)


def test_missing_page_placeholder_and_report(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws, [
        {"page": 1, "md": "Body 1", "sidecar": _sc(1)},
        {"page": 2, "sidecar": {}},  # no md -> missing
    ])
    assemble.run(ws, pdf=False, merge_pass=False)
    assert "was not transcribed" in ws.reconstructed_md.read_text(encoding="utf-8")
    assert "Missing transcriptions" in ws.report_md.read_text(encoding="utf-8")


def test_report_has_sections(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws, [
        {"page": 1, "md": "# One\n\n![c](../assets/page_0001_fig1.png)",
         "sidecar": _sc(1, figures=[{"id": "fig1", "bbox_pct": [0, 0, 100, 100], "kind": "chart", "caption": "c"}],
                        unclear=["riga 3 illeggibile"])},
    ])
    assemble.run(ws, pdf=False, merge_pass=False)
    report = ws.report_md.read_text(encoding="utf-8")
    for section in ("## Per page", "## Unclear spans", "## Figures", "riga 3 illeggibile"):
        assert section in report


def test_llm_merge_pass_uses_engine(tmp_path: Path) -> None:
    class MergeStub:
        name = "stub"

        def complete(self, prompt: str) -> str:
            return "MERGED BOUNDARY"

        def transcribe_page(self, image, prompt):  # pragma: no cover
            raise AssertionError("transcribe_page must not be called in the merge pass")

    ws = Workspace(tmp_path / "wd")
    _setup(ws, [
        {"page": 1, "md": "# One\n\ntail text", "sidecar": _sc(1, continues_to_next=True)},
        {"page": 2, "md": "head text", "sidecar": _sc(2, continues_from_prev=True)},
    ])
    assemble.run(ws, pdf=False, merge_pass=True, engine_impl=MergeStub())
    doc = ws.reconstructed_md.read_text(encoding="utf-8")
    assert "MERGED BOUNDARY" in doc
    assert "tail text head text" not in doc  # LLM result used, not deterministic


# -- units --------------------------------------------------------------------
def test_heal_deterministic_paragraph_and_dehyphenate() -> None:
    assert assemble._heal_deterministic("foo bar", "baz qux") == "foo bar baz qux"
    assert assemble._heal_deterministic("inter-", "national") == "international"


def test_split_blocks() -> None:
    assert assemble._split_blocks("a\n\nb\n\n\nc") == ["a", "b", "c"]


def test_norm_digit_insensitive() -> None:
    assert assemble._norm("Pagina 3 di 10") == assemble._norm("Pagina 4 di 10")
