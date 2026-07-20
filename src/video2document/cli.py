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

from video2document import __version__, stages
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
) -> None:
    """Decode the video into frames and build the frame manifest."""
    ws = _workspace(workdir)
    _guard(stages.extract.run, ws, video=video, fps=fps)


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
        0.985, "--ssim", min=0.0, max=1.0, help="SSIM threshold for the merge pass."
    ),
) -> None:
    """Cluster frames into pages and emit one clean image per page."""
    ws = _workspace(workdir)
    _guard(stages.pages.run, ws, viewport=viewport, hamming=hamming, ssim=ssim)


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
) -> None:
    """Transcribe each page image into Markdown + a structured sidecar."""
    ws = _workspace(workdir)
    _guard(
        stages.transcribe.run,
        ws,
        engine=engine.value,
        pages_spec=pages_spec,
        force=force,
    )


@app.command()
def assemble(
    workdir: Path = WorkdirOpt,
    pdf: bool = typer.Option(False, "--pdf", help="Also render a PDF."),
    merge_pass: bool = typer.Option(
        True,
        "--merge-pass/--no-merge-pass",
        help="Run the optional LLM page-boundary merge pass.",
    ),
) -> None:
    """Merge per-page transcriptions into the final reconstructed document."""
    ws = _workspace(workdir)
    _guard(stages.assemble.run, ws, pdf=pdf, merge_pass=merge_pass)


@app.command()
def run(
    video: Path = typer.Argument(..., help="Source video (a screen recording)."),
    workdir: Path = WorkdirOpt,
    fps: float = typer.Option(6.0, "--fps", min=0.1, help="Frame sampling rate (fps)."),
    viewport: str = typer.Option("auto", "--viewport", help="'auto' or 'x,y,w,h'."),
    hamming: int = typer.Option(6, "--hamming", min=0),
    ssim: float = typer.Option(0.985, "--ssim", min=0.0, max=1.0),
    engine: Engine = typer.Option(Engine.claude, "--engine"),
    pdf: bool = typer.Option(False, "--pdf", help="Also render a PDF."),
    merge_pass: bool = typer.Option(True, "--merge-pass/--no-merge-pass"),
) -> None:
    """Run the whole pipeline: extract -> pages -> transcribe -> assemble."""
    ws = _workspace(workdir)
    _guard(stages.extract.run, ws, video=video, fps=fps)
    _guard(stages.pages.run, ws, viewport=viewport, hamming=hamming, ssim=ssim)
    _guard(
        stages.transcribe.run, ws, engine=engine.value, pages_spec=None, force=False
    )
    _guard(stages.assemble.run, ws, pdf=pdf, merge_pass=merge_pass)
    typer.secho(f"pipeline complete — workspace: {ws.root}", fg=typer.colors.GREEN)
