"""Exception types shared across pipeline stages."""

from __future__ import annotations


class V2DError(Exception):
    """An expected, user-facing pipeline error.

    Stages raise this for conditions the user can act on: missing inputs,
    an unsupported video, a malformed manifest, an external tool not found.
    The CLI catches it and prints a clean one-line message instead of a
    traceback. Programming errors should raise the usual built-in exceptions
    so they surface with a full traceback.
    """
