"""The on-disk contract shared by every pipeline stage.

Each source video gets one *workspace* directory. Stages read the artifacts of
earlier stages and write their own, all under this root, so every stage is
independently runnable, inspectable, and resumable (see PLAN.md §2).

Layout::

    <root>/
      input/source.<ext>          original video (copied in by `extract`)
      meta/source.ffprobe.json    ffprobe dump
      frames/raw/                 extracted frames, pts-named
      frames/cropped/             frames cropped to the viewport
      manifests/
        frames.jsonl              one line per extracted frame
        viewport.json             the single crop rectangle for the whole video
        viewport_preview.png      first frame with the viewport drawn on it
        pages.jsonl               one line per detected page
      pages/page_0001.png ...     one clean image per page
      llm/
        page_0001.md              per-page transcription
        page_0001.json            per-page structured sidecar
      assets/page_0001_fig1.png   cropped figures referenced by the markdown
      out/
        reconstructed.md
        reconstructed.pdf
        report.md

This module is deliberately declarative: it knows *where* things live, not how
to produce them. Stages own the producing logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Naming template for per-page artifacts (page numbers are 1-based).
PAGE_STEM = "page_{n:04d}"

#: Recognised video extensions when locating the stored source video.
VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")


@dataclass(frozen=True)
class Workspace:
    """Paths for a single video's working directory. Construct with the root."""

    root: Path

    # -- top-level directories ------------------------------------------------
    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def meta_dir(self) -> Path:
        return self.root / "meta"

    @property
    def frames_dir(self) -> Path:
        return self.root / "frames"

    @property
    def frames_raw_dir(self) -> Path:
        return self.frames_dir / "raw"

    @property
    def frames_cropped_dir(self) -> Path:
        return self.frames_dir / "cropped"

    @property
    def manifests_dir(self) -> Path:
        return self.root / "manifests"

    @property
    def pages_dir(self) -> Path:
        return self.root / "pages"

    @property
    def llm_dir(self) -> Path:
        return self.root / "llm"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def out_dir(self) -> Path:
        return self.root / "out"

    #: Every directory the workspace owns, in creation order.
    @property
    def directories(self) -> tuple[Path, ...]:
        return (
            self.input_dir,
            self.meta_dir,
            self.frames_raw_dir,
            self.frames_cropped_dir,
            self.manifests_dir,
            self.pages_dir,
            self.llm_dir,
            self.assets_dir,
            self.out_dir,
        )

    # -- individual files -----------------------------------------------------
    @property
    def ffprobe_json(self) -> Path:
        return self.meta_dir / "source.ffprobe.json"

    @property
    def frames_manifest(self) -> Path:
        return self.manifests_dir / "frames.jsonl"

    @property
    def viewport_json(self) -> Path:
        return self.manifests_dir / "viewport.json"

    @property
    def viewport_preview(self) -> Path:
        return self.manifests_dir / "viewport_preview.png"

    @property
    def pages_manifest(self) -> Path:
        return self.manifests_dir / "pages.jsonl"

    @property
    def reconstructed_md(self) -> Path:
        return self.out_dir / "reconstructed.md"

    @property
    def reconstructed_pdf(self) -> Path:
        return self.out_dir / "reconstructed.pdf"

    @property
    def report_md(self) -> Path:
        return self.out_dir / "report.md"

    # -- per-page helpers -----------------------------------------------------
    def page_image(self, n: int) -> Path:
        return self.pages_dir / f"{PAGE_STEM.format(n=n)}.png"

    def page_md(self, n: int) -> Path:
        return self.llm_dir / f"{PAGE_STEM.format(n=n)}.md"

    def page_json(self, n: int) -> Path:
        return self.llm_dir / f"{PAGE_STEM.format(n=n)}.json"

    def figure_asset(self, page: int, fig_id: str) -> Path:
        return self.assets_dir / f"{PAGE_STEM.format(n=page)}_{fig_id}.png"

    def source_video(self, suffix: str = ".mp4") -> Path:
        """Canonical path for the stored source video (`extract` writes here)."""
        return self.input_dir / f"source{suffix}"

    def find_source_video(self) -> Path | None:
        """Return the stored source video if present, else ``None``."""
        for suffix in VIDEO_SUFFIXES:
            candidate = self.input_dir / f"source{suffix}"
            if candidate.exists():
                return candidate
        return None

    # -- lifecycle ------------------------------------------------------------
    def ensure(self) -> "Workspace":
        """Create all workspace directories (idempotent)."""
        for directory in self.directories:
            directory.mkdir(parents=True, exist_ok=True)
        return self
