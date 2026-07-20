"""Tests for the workspace path contract."""

from __future__ import annotations

from pathlib import Path

from video2document.workspace import Workspace


def test_paths_are_rooted(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    for path in (
        ws.input_dir,
        ws.meta_dir,
        ws.frames_raw_dir,
        ws.frames_cropped_dir,
        ws.manifests_dir,
        ws.pages_dir,
        ws.llm_dir,
        ws.assets_dir,
        ws.out_dir,
        ws.ffprobe_json,
        ws.frames_manifest,
        ws.viewport_json,
        ws.pages_manifest,
        ws.reconstructed_md,
        ws.report_md,
    ):
        assert tmp_path in path.parents or path == tmp_path


def test_per_page_helpers_are_zero_padded(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    assert ws.page_image(12).name == "page_0012.png"
    assert ws.page_md(12).name == "page_0012.md"
    assert ws.page_json(12).name == "page_0012.json"
    assert ws.figure_asset(12, "fig1").name == "page_0012_fig1.png"


def test_ensure_creates_every_directory(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd").ensure()
    for directory in ws.directories:
        assert directory.is_dir()


def test_find_source_video(tmp_path: Path) -> None:
    ws = Workspace(tmp_path).ensure()
    assert ws.find_source_video() is None
    ws.source_video(".mp4").write_bytes(b"fake")
    assert ws.find_source_video() == ws.source_video(".mp4")
