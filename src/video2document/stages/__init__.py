"""Pipeline stages.

Each module exposes a ``run(workspace, ...)`` entry point that the CLI calls.
Stages are CLI-agnostic (no ``typer`` imports): they take a
:class:`~video2document.workspace.Workspace` plus plain keyword arguments, read
and write files under it, and raise
:class:`~video2document.exceptions.V2DError` for user-fixable problems.
"""

from . import assemble, extract, pages, transcribe

__all__ = ["extract", "pages", "transcribe", "assemble"]
