"""Stage 2 — turn frames into one clean image per page.

Planned (M2):
  * Detect the stable viewport once (temporal-variance rectangle) and write
    ``manifests/viewport.json`` + a preview overlay.
  * Crop frames to the viewport; recompute pHash + Laplacian sharpness on the
    cropped frames.
  * Cluster consecutive frames into pages (pHash Hamming threshold; SSIM merge
    pass) and drop short transition clusters.
  * Pick the best (sharpest, mid-cluster) frame per cluster.
  * Revisit merge: collapse non-adjacent look-alike clusters (back-scrolling)
    so a page revisited later is not emitted twice.
  * Write ``pages/page_NNNN.png`` and ``manifests/pages.jsonl``.
"""

from __future__ import annotations

import logging

from video2document.workspace import Workspace

log = logging.getLogger(__name__)


def run(ws: Workspace, *, viewport: str, hamming: int, ssim: float) -> None:
    log.warning("stage 'pages' is not implemented yet (arriving in M2)")
    log.info(
        "would cluster frames (viewport=%s, hamming<=%d, ssim>=%.3f) into %s",
        viewport,
        hamming,
        ssim,
        ws.pages_dir,
    )
