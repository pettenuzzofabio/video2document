"""Scroll-aware stitching (v2, ``pages --mode scroll``).

Reassembles overlapping slices of a continuously-scrolled document into tall page
canvases. Translation-only (no scale/rotation) — enough for screen recordings, per
the deep-research prototype guidance.

Method: for each consecutive pair of (viewport-cropped) frames, estimate the
translation that aligns them by matching a central patch of one inside the other
(normalized cross-correlation, on a downscaled copy for speed). Accumulate the
offsets into canvas origins; when the overlap disappears (match score too low) start
a new segment — that is a page break. Each segment is composited into one image.

Scroll-ups (revisiting a portion) are handled naturally: the origin moves back up and
the frame is pasted over the same region (identical content), without growing the canvas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

_EST_WIDTH = 640        # downscale width for shift estimation (speed)
_PATCH_H_FRAC = 0.40    # central patch size, as a fraction of the frame
_PATCH_W_FRAC = 0.70
_MIN_SCORE = 0.45       # min normalized correlation to accept an overlap
_MIN_PATCH_STD = 6.0    # min patch texture (stddev) to trust a match
_MAX_SEG_FRAMES = 400   # safety cap on frames per segment


@dataclass
class Placement:
    index: int   # frame index
    ox: float    # canvas origin x (full-res px)
    oy: float    # canvas origin y (full-res px)


def estimate_shift(a, b) -> tuple[float, float, float]:
    """Offset to add to origin(a) to get origin(b), in full-res px, plus a score.

    ``a``, ``b`` are equal-size grayscale uint8 arrays. Matches a central patch of
    ``a`` inside ``b``; the score is the peak normalized correlation (0..1).
    """
    import cv2
    import numpy as np

    height, width = a.shape[:2]
    scale = _EST_WIDTH / width
    small = (_EST_WIDTH, max(1, round(height * scale)))
    a_s = cv2.resize(a, small, interpolation=cv2.INTER_AREA)
    b_s = cv2.resize(b, small, interpolation=cv2.INTER_AREA)

    sh, sw = a_s.shape
    ph = max(8, int(sh * _PATCH_H_FRAC))
    pw = max(8, int(sw * _PATCH_W_FRAC))
    px, py = (sw - pw) // 2, (sh - ph) // 2
    patch = a_s[py : py + ph, px : px + pw]

    if float(patch.std()) < _MIN_PATCH_STD:
        # near-blank patch: template matching would lock onto noise -> unreliable
        return 0.0, 0.0, 0.0

    result = cv2.matchTemplate(b_s, patch, cv2.TM_CCOEFF_NORMED)
    _, score, _, max_loc = cv2.minMaxLoc(result)
    mx, my = max_loc  # top-left where a's patch sits in b (downscaled)
    # content at a(px,py) == b(mx,my)  =>  origin_b = origin_a + (px-mx, py-my)
    return (px - mx) / scale, (py - my) / scale, float(score)


def stitch(frames_gray, *, min_score: float = _MIN_SCORE) -> list[list[Placement]]:
    """Group frames into segments (pages) with per-frame canvas origins."""
    if not frames_gray:
        return []
    segments: list[list[Placement]] = []
    current = [Placement(0, 0.0, 0.0)]
    ox = oy = 0.0
    for i in range(1, len(frames_gray)):
        dx, dy, score = estimate_shift(frames_gray[i - 1], frames_gray[i])
        if score < min_score or len(current) >= _MAX_SEG_FRAMES:
            segments.append(current)
            current = [Placement(i, 0.0, 0.0)]
            ox = oy = 0.0
        else:
            ox += dx
            oy += dy
            current.append(Placement(i, ox, oy))
    segments.append(current)
    return segments


def composite(segment: list[Placement], frames_color):
    """Composite one segment's frames onto a single canvas (temporal paste order)."""
    from PIL import Image

    fw, fh = frames_color[segment[0].index].size
    min_x = min(p.ox for p in segment)
    min_y = min(p.oy for p in segment)
    max_x = max(p.ox + fw for p in segment)
    max_y = max(p.oy + fh for p in segment)
    canvas = Image.new("RGB", (round(max_x - min_x), round(max_y - min_y)), (255, 255, 255))
    for p in segment:
        canvas.paste(frames_color[p.index], (round(p.ox - min_x), round(p.oy - min_y)))
    return canvas
