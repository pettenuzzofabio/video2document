"""Stage 3 — transcribe each page image with a vision-capable CLI LLM.

Planned (M3):
  * For each ``pages/page_NNNN.png`` without an up-to-date transcription, call
    the selected engine (default ``claude -p``) with the page image and a strict
    no-guess prompt (PLAN.md §4).
  * Parse the sentinel-delimited response into page Markdown + a JSON sidecar
    (figures with bboxes, unclear spans, header/footer, continuity flags);
    validate the sidecar and retry once on malformed output.
  * Crop figure bboxes (+padding) into ``assets/`` and rewrite figure
    placeholders in the Markdown.
  * Skip pages already transcribed unless ``force``; honour a ``pages`` selection.
"""

from __future__ import annotations

import logging

from video2document.workspace import Workspace

log = logging.getLogger(__name__)


def run(
    ws: Workspace,
    *,
    engine: str,
    pages_spec: str | None,
    force: bool,
) -> None:
    log.warning("stage 'transcribe' is not implemented yet (arriving in M3)")
    log.info(
        "would transcribe pages=%s with engine=%s (force=%s) into %s",
        pages_spec or "all",
        engine,
        force,
        ws.llm_dir,
    )
