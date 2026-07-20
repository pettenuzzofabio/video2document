"""Command-line entry point for video2document (the ``v2d`` command).

Five staged subcommands connected by the on-disk workspace contract
(see :mod:`video2document.workspace` and PLAN.md):

    v2d extract     decode video -> frames + frame manifest        (M1)
    v2d pages       frames -> one clean image per page             (M2)
    v2d transcribe  page images -> per-page markdown + sidecar     (M3)
    v2d assemble    per-page markdown -> reconstructed document    (M4)
    v2d run         extract -> pages -> transcribe -> assemble

Every stage reads and writes files under a single ``--workdir``, so stages can
be run one at a time, inspected, and resumed. During M0 every stage is a stub
that reports what it *would* do.
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import typer

from video2document import __version__, delivery, stages
from video2document.exceptions import V2DError
from video2document.workspace import Workspace

log = logging.getLogger("video2document")

DEFAULT_WORKDIR = Path("work")

app = typer.Typer(
    name="v2d",
    help="Reconstruct a document from a screen recording of it being scrolled.",
    no_args_is_help=True,
    add_completion=False,
)


class Engine(str, Enum):
    """Vision-LLM backend used by the transcribe stage."""

    claude = "claude"
    codex = "codex"
    llm = "llm"


class PagesMode(str, Enum):
    """How `pages` turns frames into pages."""

    pagefit = "pagefit"  # each page fully visible at some moment (default)
    scroll = "scroll"    # continuous zoomed scroll → stitch overlapping slices


class Rotate(str, Enum):
    """Bring rotated pages upright (e.g. a PDF rendered rotated to fill the screen)."""

    none = "none"
    cw = "cw"
    ccw = "ccw"
    d180 = "180"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"v2d {__version__}")
        raise typer.Exit()


def _workspace(workdir: Path) -> Workspace:
    return Workspace(workdir.resolve()).ensure()


def _guard(stage: Callable[..., None], *args: object, **kwargs: object) -> None:
    """Run a stage, turning an expected error into a clean CLI failure."""
    try:
        stage(*args, **kwargs)
    except V2DError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


# -- global options ----------------------------------------------------------
@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable debug logging."
    ),
) -> None:
    _setup_logging(verbose)


# -- workdir option, shared shape --------------------------------------------
WorkdirOpt = typer.Option(DEFAULT_WORKDIR, "--workdir", "-w", help="Workspace directory.")


# -- stages ------------------------------------------------------------------
@app.command()
def extract(
    video: Path = typer.Argument(..., help="Source video (a screen recording)."),
    workdir: Path = WorkdirOpt,
    fps: float = typer.Option(6.0, "--fps", min=0.1, help="Frame sampling rate (fps)."),
    decimate: bool = typer.Option(
        True,
        "--decimate/--no-decimate",
        help="Drop near-identical frames at decode (mpdecimate).",
    ),
) -> None:
    """Decode the video into frames and build the frame manifest."""
    ws = _workspace(workdir)
    _guard(stages.extract.run, ws, video=video, fps=fps, decimate=decimate)


@app.command()
def pages(
    workdir: Path = WorkdirOpt,
    viewport: str = typer.Option(
        "auto", "--viewport", help="'auto' or an explicit crop 'x,y,w,h'."
    ),
    hamming: int = typer.Option(
        6, "--hamming", min=0, help="Max pHash Hamming distance within one page."
    ),
    ssim: float = typer.Option(
        0.985, "--ssim", min=0.0, max=1.0, help="SSIM threshold (reserved for the optional merge pass)."
    ),
    min_page_ms: float = typer.Option(
        400.0,
        "--min-page-ms",
        min=0.0,
        help="Minimum time a page must stay visible to count (briefer = transition).",
    ),
    mode: PagesMode = typer.Option(
        PagesMode.pagefit,
        "--mode",
        help="'pagefit' (each page fully visible) or 'scroll' (stitch a continuous zoomed scroll).",
    ),
    rotate: Rotate = typer.Option(
        Rotate.none, "--rotate", help="Bring rotated pages upright: none|cw|ccw|180."
    ),
) -> None:
    """Cluster frames into pages and emit one clean image per page."""
    ws = _workspace(workdir)
    _guard(
        stages.pages.run,
        ws,
        viewport=viewport,
        hamming=hamming,
        ssim=ssim,
        min_page_ms=min_page_ms,
        mode=mode.value,
        rotate=rotate.value,
    )


@app.command()
def transcribe(
    workdir: Path = WorkdirOpt,
    engine: Engine = typer.Option(
        Engine.claude, "--engine", help="Vision-LLM backend."
    ),
    pages_spec: Optional[str] = typer.Option(
        None, "--pages", help="Page selection, e.g. '3,7-9' (default: all)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-transcribe pages that already have output."
    ),
    model: Optional[str] = typer.Option(
        None, "--model", help="Model id for the engine (optional; engine default otherwise)."
    ),
) -> None:
    """Transcribe each page image into Markdown + a structured sidecar."""
    ws = _workspace(workdir)
    _guard(
        stages.transcribe.run,
        ws,
        engine=engine.value,
        pages_spec=pages_spec,
        force=force,
        model=model,
    )


@app.command()
def assemble(
    workdir: Path = WorkdirOpt,
    pdf: bool = typer.Option(False, "--pdf", help="Also render a PDF."),
    merge_pass: bool = typer.Option(
        True,
        "--merge-pass/--no-merge-pass",
        help="Refine split page boundaries with a small LLM merge (only when boundaries exist).",
    ),
    engine: Engine = typer.Option(Engine.claude, "--engine", help="Engine for the merge pass."),
    model: Optional[str] = typer.Option(None, "--model", help="Model id for the merge pass (optional)."),
) -> None:
    """Merge per-page transcriptions into the final reconstructed document."""
    ws = _workspace(workdir)
    _guard(
        stages.assemble.run,
        ws,
        pdf=pdf,
        merge_pass=merge_pass,
        engine=engine.value,
        model=model,
    )


@app.command()
def details(
    workdir: Path = WorkdirOpt,
    details_dir: Optional[Path] = typer.Option(
        None, "--details", help="Folder of hi-res diagram photos (default <workdir>/details)."
    ),
    engine: Engine = typer.Option(Engine.claude, "--engine", help="Engine for the extraction pass."),
    model: Optional[str] = typer.Option(None, "--model", help="Model id (optional)."),
    min_matches: int = typer.Option(
        15, "--min-matches", min=1, help="Min ORB inliers to accept a photo↔page match."
    ),
) -> None:
    """Match supplied hi-res diagram photos to pages and extract their data into them."""
    ws = _workspace(workdir)
    _guard(
        stages.details.run,
        ws,
        details_dir=str(details_dir) if details_dir else None,
        engine=engine.value,
        model=model,
        min_matches=min_matches,
    )


@app.command()
def run(
    target: Path = typer.Argument(
        ..., help="A video file, or a folder containing the video (+ optional hi-res diagram images)."
    ),
    workdir: Optional[Path] = typer.Option(
        None, "--workdir", "-w", help="Workspace dir (default: <video>.v2d next to the video)."
    ),
    fps: float = typer.Option(6.0, "--fps", min=0.1, help="Frame sampling rate (fps)."),
    viewport: str = typer.Option("auto", "--viewport", help="'auto' or 'x,y,w,h'."),
    hamming: int = typer.Option(6, "--hamming", min=0),
    ssim: float = typer.Option(0.985, "--ssim", min=0.0, max=1.0),
    engine: Engine = typer.Option(Engine.claude, "--engine"),
    model: Optional[str] = typer.Option(None, "--model"),
    pdf: bool = typer.Option(False, "--pdf", help="Also render a PDF."),
    merge_pass: bool = typer.Option(True, "--merge-pass/--no-merge-pass"),
    decimate: bool = typer.Option(True, "--decimate/--no-decimate"),
    mode: PagesMode = typer.Option(PagesMode.pagefit, "--mode"),
    rotate: Rotate = typer.Option(Rotate.none, "--rotate"),
    auto_details: bool = typer.Option(
        True, "--details/--no-details",
        help="Match hi-res images found next to the video as diagram details.",
    ),
    deliver: bool = typer.Option(
        True, "--deliver/--no-deliver",
        help="Write the result next to the inputs as <video>.md (+ <video>_assets/).",
    ),
) -> None:
    """Full pipeline. Point it at a video, or a folder holding the video (+ optional
    hi-res diagram photos); the finished <video>.md (with images) is written beside the
    inputs."""
    try:
        video = delivery.find_video(target)
    except V2DError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    folder = video.parent
    ws = _workspace(workdir if workdir else folder / f"{video.stem}.v2d")

    _guard(stages.extract.run, ws, video=video, fps=fps, decimate=decimate)
    _guard(
        stages.pages.run,
        ws, viewport=viewport, hamming=hamming, ssim=ssim,
        mode=mode.value, rotate=rotate.value,
    )
    _guard(
        stages.transcribe.run, ws, engine=engine.value, pages_spec=None, force=False, model=model
    )

    if auto_details and delivery.folder_images(folder):
        try:  # a stray non-diagram image shouldn't abort the whole run
            stages.details.run(ws, details_dir=str(folder), engine=engine.value, model=model)
        except V2DError as exc:
            typer.secho(f"note: details step skipped ({exc})", fg=typer.colors.YELLOW, err=True)

    _guard(stages.assemble.run, ws, pdf=pdf, merge_pass=merge_pass, engine=engine.value, model=model)

    if deliver:
        out = delivery.deliver(ws, folder, video.stem, pdf=pdf)
        typer.secho(f"done — {out}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"pipeline complete — workspace: {ws.root}", fg=typer.colors.GREEN)
