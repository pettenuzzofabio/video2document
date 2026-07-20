"""Stage 4 — merge per-page transcriptions into the final document.

Planned (M4):
  * Concatenate page Markdown in page order into ``out/reconstructed.md``.
  * Boundary healing: join paragraphs/tables split across a page break using the
    continuity flags (deterministic first, optional LLM merge pass).
  * Header/footer suppression: verify the LLM-declared running headers/footers by
    digit-insensitive repetition across pages before removing them from the body.
  * Write ``out/report.md`` (page count, confidence, unclear spans, figures).
  * ``--pdf``: render the Markdown to ``out/reconstructed.pdf`` (pandoc/weasyprint).
"""

from __future__ import annotations

import logging

from video2document.workspace import Workspace

log = logging.getLogger(__name__)


def run(ws: Workspace, *, pdf: bool, merge_pass: bool) -> None:
    log.warning("stage 'assemble' is not implemented yet (arriving in M4)")
    log.info(
        "would assemble %s (pdf=%s, merge_pass=%s)",
        ws.reconstructed_md,
        pdf,
        merge_pass,
    )
