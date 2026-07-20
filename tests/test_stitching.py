"""Tests for scroll-aware stitching (translation mosaic)."""

from __future__ import annotations

import numpy as np
from PIL import Image

from video2document import stitching


def _texture(h: int, w: int, seed: int = 0) -> np.ndarray:
    """A non-periodic textured image — a sharp, unambiguous match target."""
    return np.random.default_rng(seed).integers(0, 256, (h, w), dtype=np.uint8)


def test_estimate_shift_recovers_known_offset() -> None:
    src = _texture(1200, 800)
    a = src[0:600, :]
    b = src[120:720, :]  # scrolled down by 120 px, no horizontal move
    ox, oy, score = stitching.estimate_shift(a, b)
    assert score > 0.6
    assert abs(oy - 120) < 15
    assert abs(ox) < 15


def test_stitch_reconstructs_a_vertical_scroll() -> None:
    src = _texture(1600, 800)
    win, step = 600, 150
    offsets = list(range(0, 1600 - win + 1, step))  # overlapping windows
    frames = [src[o : o + win, :] for o in offsets]

    segments = stitching.stitch(frames, min_score=0.4)
    assert len(segments) == 1

    seg = segments[0]
    assert seg[0].oy == 0
    assert abs(seg[-1].oy - offsets[-1]) < 30  # accumulated offset ~= real scroll

    color = [Image.fromarray(f).convert("RGB") for f in frames]
    canvas = stitching.composite(seg, color)
    assert canvas.size[0] == 800
    assert abs(canvas.size[1] - (win + offsets[-1])) < 30  # ~= covered source height


def test_stitch_breaks_on_unrelated_frames() -> None:
    f1 = _texture(600, 800, seed=1)
    f2 = _texture(600, 800, seed=2)  # independent -> uncorrelated
    assert len(stitching.stitch([f1, f2], min_score=0.5)) == 2
