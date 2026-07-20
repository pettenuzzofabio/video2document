"""Tests for folder-mode delivery helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from video2document import delivery
from video2document.exceptions import V2DError
from video2document.workspace import Workspace


def test_find_video_file(tmp_path: Path) -> None:
    v = tmp_path / "a.mp4"
    v.write_bytes(b"x")
    assert delivery.find_video(v) == v.resolve()


def test_find_video_in_folder(tmp_path: Path) -> None:
    v = tmp_path / "clip.mkv"
    v.write_bytes(b"x")
    (tmp_path / "diagram.png").write_bytes(b"x")  # not a video
    assert delivery.find_video(tmp_path) == v.resolve()


def test_find_video_none_raises(tmp_path: Path) -> None:
    with pytest.raises(V2DError):
        delivery.find_video(tmp_path)


def test_folder_images_top_level_only(tmp_path: Path) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "d1.png").write_bytes(b"x")
    (tmp_path / "d2.JPG").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.png").write_bytes(b"x")
    names = sorted(p.name for p in delivery.folder_images(tmp_path))
    assert names == ["d1.png", "d2.JPG"]


def test_deliver_rewrites_paths_and_copies_assets(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "wd").ensure()
    (ws.assets_dir / "page_0001_fig1.png").write_bytes(b"img")
    ws.reconstructed_md.write_text(
        "# Title\n\n![chart](../assets/page_0001_fig1.png)\n", encoding="utf-8"
    )
    folder = tmp_path / "folder"
    folder.mkdir()

    out = delivery.deliver(ws, folder, "myvid", pdf=False)

    assert out == folder / "myvid.md"
    md = out.read_text(encoding="utf-8")
    assert "myvid_assets/page_0001_fig1.png" in md
    assert "../assets/" not in md
    assert (folder / "myvid_assets" / "page_0001_fig1.png").is_file()
