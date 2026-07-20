"""End-to-end pipeline test: real extract + pages, stubbed transcribe, real assemble.

Exercises the whole data flow (video -> reconstructed.md) without any LLM call by
substituting a stub engine that emits per-page content keyed off the prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

from video2document.stages import assemble, extract, pages, transcribe
from video2document.workspace import Workspace


class PipelineStub:
    """Emits valid sentinel output with content specific to each page."""

    name = "stub"

    def transcribe_page(self, image: Path, prompt: str) -> str:
        match = re.search(r"This is page (\d+)", prompt)
        n = int(match.group(1)) if match else 1
        return (
            "===V2D_MARKDOWN===\n"
            f"# Page {n}\n\nBody of page {n}.\n"
            "===V2D_JSON===\n"
            f'{{"page": {n}, "language": "en", "confidence": "high", "figures": [], '
            '"header": null, "footer": null, "page_number": null, "unclear": [], '
            '"continues_from_prev": false, "continues_to_next": false}\n'
        )

    def complete(self, prompt: str) -> str:  # pragma: no cover
        return ""


def test_full_pipeline_en_simple(tmp_path: Path, make_fixture) -> None:
    video = make_fixture("en_simple")
    ws = Workspace(tmp_path / "wd").ensure()

    extract.run(ws, video=video, fps=6, decimate=True)
    pages.run(ws, viewport="auto", hamming=6, ssim=0.985)
    transcribe.run(ws, engine="stub", pages_spec=None, force=False, engine_impl=PipelineStub())
    assemble.run(ws, pdf=False, merge_pass=False)

    doc = ws.reconstructed_md.read_text(encoding="utf-8")
    for n in (1, 2, 3):
        assert f"# Page {n}" in doc
    assert doc.index("# Page 1") < doc.index("# Page 2") < doc.index("# Page 3")
    assert ws.report_md.exists()
