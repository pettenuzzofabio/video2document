"""Tests for the details stage (hi-res diagram photo -> page matching + extraction)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from video2document.exceptions import V2DError
from video2document.stages import details
from video2document.workspace import Workspace


class StubEngine:
    name = "stub"

    def transcribe_page(self, image: Path, prompt: str) -> str:
        return "- A -> B\n- C -> D"

    def complete(self, prompt: str) -> str:  # pragma: no cover
        return ""


def _draw_diagram(path: Path, variant: int, size=(600, 800)) -> None:
    """A distinct, feature-rich synthetic 'diagram' (boxes + labels + lines)."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for i in range(9):
        x = 40 + (i % 3) * 180 + variant * 13
        y = 40 + (i // 3) * 190
        d.rectangle([x, y, x + 150, y + 110], outline="black", width=4)
        d.text((x + 12, y + 14), f"NODE-{variant}-{i}", fill="black")
        d.line([x, y + 110, x + 150, y], fill="black", width=2)
    img.save(path)


def _setup(ws: Workspace) -> None:
    ws.ensure()
    records = []
    for p in (1, 2):
        _draw_diagram(ws.page_image(p), variant=p)
        ws.page_md(p).write_text(f"# Page {p}\n\nText {p}.", encoding="utf-8")
        records.append({"page": p, "image": str(ws.page_image(p).relative_to(ws.root)), "detail_images": []})
    with ws.pages_manifest.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_details_matches_page_and_extracts(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws)
    photos = tmp_path / "photos"
    photos.mkdir()
    # hi-res photo == page 2's diagram, upscaled 1.5x
    Image.open(ws.page_image(2)).resize((900, 1200)).save(photos / "diagram.png")

    details.run(ws, details_dir=str(photos), engine="stub", min_matches=10, engine_impl=StubEngine())

    md2 = ws.page_md(2).read_text(encoding="utf-8")
    assert "Diagram detail" in md2
    assert "A -> B" in md2
    assert "../assets/page_0002_detail1.png" in md2
    assert ws.figure_asset(2, "detail1").exists()
    assert "Diagram detail" not in ws.page_md(1).read_text(encoding="utf-8")  # page 1 untouched

    records = [json.loads(x) for x in ws.pages_manifest.read_text().splitlines() if x.strip()]
    page2 = next(r for r in records if r["page"] == 2)
    assert page2["detail_images"] == ["assets/page_0002_detail1.png"]


def test_details_unmatched_raises(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd")
    _setup(ws)
    photos = tmp_path / "photos"
    photos.mkdir()
    noise = np.random.default_rng(9).integers(0, 256, (400, 400, 3), dtype=np.uint8)
    Image.fromarray(noise).save(photos / "unrelated.png")

    with pytest.raises(V2DError):
        details.run(ws, details_dir=str(photos), engine="stub", min_matches=15, engine_impl=StubEngine())
