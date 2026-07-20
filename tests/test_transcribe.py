"""Tests for stage 3 (transcribe): parsing, validation, figures, resume, selection.

The LLM is replaced by a stub engine so the plumbing is exercised deterministically
without any model call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from video2document.exceptions import V2DError
from video2document.stages import transcribe
from video2document.workspace import Workspace

VALID_RESPONSE = """\
some preamble the model might add
===V2D_MARKDOWN===
# Titolo della pagina

Testo di esempio con un accento: perché.

![Grafico vendite](FIGURE:fig1)
===V2D_JSON===
{"page": 1, "language": "it", "confidence": "high",
 "figures": [{"id": "fig1", "bbox_pct": [10, 40, 90, 85], "caption": "Grafico vendite", "kind": "chart"}],
 "header": null, "footer": "Pagina 1", "page_number": "1",
 "unclear": [], "continues_from_prev": false, "continues_to_next": false}
"""


class StubEngine:
    name = "stub"

    def __init__(self, responses):
        self._responses = responses if isinstance(responses, list) else [responses]
        self.calls = 0

    def transcribe_page(self, image: Path, prompt: str) -> str:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


def _setup_pages(ws: Workspace, n: int = 1, size=(400, 600)) -> None:
    ws.ensure()
    records = []
    for page in range(1, n + 1):
        Image.new("RGB", size, "white").save(ws.page_image(page))
        records.append({
            "page": page, "source_frame_id": 0, "pts_ms": 0.0,
            "image": str(ws.page_image(page).relative_to(ws.root)),
            "cluster_size": 1, "revisit_pts_ms": [], "detail_images": [],
        })
    with ws.pages_manifest.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def test_transcribe_writes_outputs_and_crops_figure(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup_pages(ws, 1)
    stub = StubEngine(VALID_RESPONSE)

    transcribe.run(ws, engine="stub", pages_spec=None, force=False, engine_impl=stub)

    assert stub.calls == 1
    md = ws.page_md(1).read_text(encoding="utf-8")
    assert "../assets/page_0001_fig1.png" in md
    assert "FIGURE:fig1" not in md
    assert "perché" in md
    assert ws.figure_asset(1, "fig1").exists()

    sidecar = json.loads(ws.page_json(1).read_text(encoding="utf-8"))
    assert sidecar["page"] == 1
    assert sidecar["footer"] == "Pagina 1"
    # cropped figure is smaller than the full page
    assert Image.open(ws.figure_asset(1, "fig1")).size[1] < 600


def test_resume_skips_then_force_reruns(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup_pages(ws, 1)

    first = StubEngine(VALID_RESPONSE)
    transcribe.run(ws, engine="stub", pages_spec=None, force=False, engine_impl=first)
    assert first.calls == 1

    again = StubEngine(VALID_RESPONSE)
    transcribe.run(ws, engine="stub", pages_spec=None, force=False, engine_impl=again)
    assert again.calls == 0  # already transcribed -> skipped

    forced = StubEngine(VALID_RESPONSE)
    transcribe.run(ws, engine="stub", pages_spec=None, force=True, engine_impl=forced)
    assert forced.calls == 1


def test_page_selection(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup_pages(ws, 3)
    stub = StubEngine(VALID_RESPONSE)

    transcribe.run(ws, engine="stub", pages_spec="2,3", force=False, engine_impl=stub)

    assert not ws.page_md(1).exists()
    assert ws.page_md(2).exists()
    assert ws.page_md(3).exists()
    assert json.loads(ws.page_json(2).read_text())["page"] == 2  # page number enforced


def test_malformed_output_retries_then_records_error(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup_pages(ws, 1)
    stub = StubEngine(["garbage without sentinels", "still no sentinels"])

    with pytest.raises(V2DError):
        transcribe.run(ws, engine="stub", pages_spec=None, force=False, engine_impl=stub)

    assert stub.calls == 2  # one retry
    assert not ws.page_md(1).exists()
    assert (ws.llm_dir / "page_0001.error.txt").exists()


def test_degenerate_bbox_falls_back_to_full_page(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup_pages(ws, 1, size=(400, 600))
    bad = VALID_RESPONSE.replace("[10, 40, 90, 85]", "[90, 40, 10, 85]")  # x1 > x2
    transcribe.run(ws, engine="stub", pages_spec=None, force=False, engine_impl=StubEngine(bad))
    # fell back to the full page
    assert Image.open(ws.figure_asset(1, "fig1")).size == (400, 600)


def test_parse_page_spec() -> None:
    assert transcribe._parse_page_spec("3,7-9") == {3, 7, 8, 9}
    assert transcribe._parse_page_spec("1") == {1}


def test_split_sections_ignores_preamble_and_fences() -> None:
    md, js = transcribe._split_sections(VALID_RESPONSE)
    assert md.startswith("# Titolo")
    assert json.loads(js)["language"] == "it"
