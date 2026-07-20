"""Folder-mode helpers for `v2d run`.

The default UX: put a video (+ optional hi-res diagram images) in a folder, run the
tool, and get the finished document back in that same folder as ``<video>.md`` with its
images alongside in ``<video>_assets/``. These helpers locate the video, gather the
sibling images (candidate diagram photos), and deliver the result next to the inputs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from video2document.exceptions import V2DError
from video2document.workspace import VIDEO_SUFFIXES, Workspace

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def find_video(target: Path) -> Path:
    """Resolve a video file, or the (first) video inside a folder."""
    target = Path(target).expanduser().resolve()
    if target.is_file():
        return target
    if target.is_dir():
        videos = sorted(p for p in target.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
        if not videos:
            raise V2DError(f"no video found in folder: {target}")
        return videos[0]
    raise V2DError(f"not found: {target}")


def folder_images(folder: Path) -> list[Path]:
    """Top-level image files in a folder (candidate hi-res diagram photos).

    Only immediate files are returned; subfolders (the workspace, delivered assets) are
    ignored, so re-runs don't re-ingest already-delivered images.
    """
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def deliver(ws: Workspace, folder: Path, stem: str, *, pdf: bool = False) -> Path:
    """Write the finished document beside the inputs.

    Produces ``<stem>.md`` in *folder*, copies referenced figures to ``<stem>_assets/``
    (rewriting the Markdown image paths so they resolve from the .md's location), and
    copies the PDF to ``<stem>.pdf`` when requested. Returns the delivered .md path.
    """
    if not ws.reconstructed_md.exists():
        raise V2DError("nothing to deliver — run `assemble` first")

    markdown = ws.reconstructed_md.read_text(encoding="utf-8")
    if ws.assets_dir.exists() and any(ws.assets_dir.iterdir()):
        assets_name = f"{stem}_assets"
        dst = folder / assets_name
        dst.mkdir(exist_ok=True)
        for asset in ws.assets_dir.iterdir():
            if asset.is_file():
                shutil.copyfile(asset, dst / asset.name)
        markdown = markdown.replace("../assets/", f"{assets_name}/")

    md_out = folder / f"{stem}.md"
    md_out.write_text(markdown, encoding="utf-8")
    if pdf and ws.reconstructed_pdf.exists():
        shutil.copyfile(ws.reconstructed_pdf, folder / f"{stem}.pdf")
    return md_out
