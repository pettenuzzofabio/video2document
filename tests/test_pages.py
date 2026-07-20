"""Tests for stage 2 (pages): viewport, run grouping, persistence, revisit merge."""

from __future__ import annotations

import json
from pathlib import Path

import imagehash
import numpy as np
import pytest

from video2document.stages import extract, pages
from video2document.workspace import Workspace


# -- unit: run grouping (anchored) -------------------------------------------
def test_group_runs_anchored() -> None:
    h0 = imagehash.hex_to_hash("0000000000000000")
    hf = imagehash.hex_to_hash("ffffffffffffffff")  # Hamming 64 from h0
    # two stable views separated by a change, then back to the first view
    runs = pages._group_runs([h0, h0, hf, hf, h0], hamming=6)
    assert runs == [[0, 1], [2, 3], [4]]


# -- unit: persistence from pts gaps -----------------------------------------
def test_compute_persistence() -> None:
    frames = [{"pts_ms": 0.0}, {"pts_ms": 1000.0}, {"pts_ms": 1200.0}]
    pages._compute_persistence(frames, duration_ms=2000.0)
    assert [f["persist_ms"] for f in frames] == [1000.0, 200.0, 800.0]


# -- unit: classify by persistence -------------------------------------------
def test_classify_pages_vs_transitions() -> None:
    frames = [
        {"persist_ms": 1000.0, "pts_ms": 0.0},    # page
        {"persist_ms": 150.0, "pts_ms": 1000.0},  # transition
        {"persist_ms": 900.0, "pts_ms": 1150.0},  # page
    ]
    runs = [[0], [1], [2]]
    page_runs = pages._classify(frames, runs, min_page_ms=400.0)
    assert len(page_runs) == 2
    assert [f["role"] for f in frames] == ["page", "transition", "page"]


# -- unit: revisit merge collapses look-alikes -------------------------------
def test_revisit_merge_dedupes_and_orders() -> None:
    a = imagehash.hex_to_hash("0000000000000000")
    b = imagehash.hex_to_hash("ffffffffffffffff")
    # best frames for runs visiting pages: A, B, A  -> 2 distinct
    hashes = [a, b, a]
    frames = [
        {"laplacian_var": 10.0}, {"laplacian_var": 10.0}, {"laplacian_var": 20.0},
    ]
    page_runs = [
        {"best_idx": 0, "first_pts": 0.0, "frames": [0]},
        {"best_idx": 1, "first_pts": 500.0, "frames": [1]},
        {"best_idx": 2, "first_pts": 900.0, "frames": [2]},
    ]
    distinct = pages._revisit_merge(page_runs, frames, hashes, hamming=6)
    assert len(distinct) == 2
    # page A was revisited; sharper revisit (var 20) becomes the kept best
    page_a = min(distinct, key=lambda d: d["first_pts"])
    assert page_a["best_idx"] == 2
    assert page_a["revisit_pts"] == [900.0]


# -- unit: viewport from a synthetic stack -----------------------------------
def test_viewport_from_stack_finds_changing_region() -> None:
    frames = []
    for i in range(8):
        f = np.full((100, 100), 50, dtype=np.uint8)  # static border value
        f[30:70, 20:60] = (i * 29) % 256              # a changing inner rectangle
        frames.append(f)
    rect = pages._viewport_from_stack(frames)
    assert rect is not None
    x, y, w, h = rect
    # bbox should be near the changing region (20..60, 30..70), allowing morphology slack
    assert 10 <= x <= 25 and 20 <= y <= 35
    assert 30 <= w <= 55 and 30 <= h <= 55


def test_apply_rotation_dimensions() -> None:
    from PIL import Image

    img = Image.new("RGB", (100, 60))  # landscape
    assert pages._apply_rotation(img, "cw").size == (60, 100)
    assert pages._apply_rotation(img, "ccw").size == (60, 100)
    assert pages._apply_rotation(img, "180").size == (100, 60)
    assert pages._apply_rotation(img, "none").size == (100, 60)


def test_looks_rotated_heuristic() -> None:
    upright = np.full((200, 300), 255, np.uint8)
    upright[::12, :] = 0  # horizontal text-like lines -> rows vary
    assert not pages._looks_rotated(upright)

    rotated = np.full((200, 300), 255, np.uint8)
    rotated[:, ::12] = 0  # vertical lines -> columns vary
    assert pages._looks_rotated(rotated)


def test_viewport_from_stack_returns_none_when_static() -> None:
    frames = [np.full((50, 50), 120, dtype=np.uint8) for _ in range(5)]
    assert pages._viewport_from_stack(frames) is None


# -- integration: end to end on generated fixtures ---------------------------
def _pages_count(tmp_path: Path, video: Path) -> int:
    ws = Workspace(tmp_path / "wd").ensure()
    extract.run(ws, video=video, fps=6, decimate=True)
    pages.run(ws, viewport="auto", hamming=6, ssim=0.985)
    return len(sorted(ws.pages_dir.glob("page_*.png")))


def test_pages_en_simple(tmp_path: Path, make_fixture) -> None:
    video = make_fixture("en_simple")
    ws = Workspace(tmp_path / "wd").ensure()
    extract.run(ws, video=video, fps=6, decimate=True)
    pages.run(ws, viewport="auto", hamming=6, ssim=0.985)

    assert len(sorted(ws.pages_dir.glob("page_*.png"))) == 3
    assert ws.viewport_preview.exists()
    records = [json.loads(x) for x in ws.pages_manifest.read_text().splitlines() if x.strip()]
    assert [r["page"] for r in records] == [1, 2, 3]


def test_pages_backscroll_merges_revisits(tmp_path: Path, make_fixture) -> None:
    # view order [0,1,2,1,0] -> 5 page runs must collapse to 3 distinct pages
    assert _pages_count(tmp_path, make_fixture("en_backscroll")) == 3
