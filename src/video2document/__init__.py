"""video2document — reconstruct a document from a screen recording of it being scrolled.

See PLAN.md for the architecture. The pipeline runs as staged subcommands
(``v2d extract | pages | transcribe | assemble | run``) that communicate through
an on-disk workspace contract (see :mod:`video2document.workspace`).
"""

__version__ = "0.1.0"
