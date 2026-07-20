"""Vision-LLM CLI backends for the transcribe stage.

Each engine turns (page image, instruction prompt) into the model's raw text
response. The stage parses that response; engines only handle invocation and
image delivery. Adding a backend is the only pluggable seam in v1.

Only ClaudeEngine is validated in this environment; Codex/Llm adapters follow
their documented CLIs and are best-effort until exercised.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

from video2document.exceptions import V2DError

DEFAULT_TIMEOUT_S = 300


@runtime_checkable
class Engine(Protocol):
    name: str

    def transcribe_page(self, image: Path, prompt: str) -> str:
        """Return the model's raw text response for one page image."""


def _require(cli: str) -> str:
    path = shutil.which(cli)
    if not path:
        raise V2DError(f"'{cli}' not found on PATH — install it or choose another --engine")
    return path


def _run(cmd: list[str], timeout: int, label: str) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise V2DError(f"{label} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise V2DError(f"{label} failed (exit {proc.returncode}): {proc.stderr[-500:].strip()}")
    return proc.stdout


class ClaudeEngine:
    name = "claude"

    def __init__(self, model: str | None = None, timeout: int = DEFAULT_TIMEOUT_S):
        self.model = model
        self.timeout = timeout

    def transcribe_page(self, image: Path, prompt: str) -> str:
        cli = _require("claude")
        full = f"Read the image at {image}\n\n{prompt}"
        cmd = [cli, "-p", full, "--allowedTools", "Read", "--output-format", "text"]
        if self.model:
            cmd += ["--model", self.model]
        return _run(cmd, self.timeout, "claude")


class CodexEngine:
    name = "codex"

    def __init__(self, model: str | None = None, timeout: int = DEFAULT_TIMEOUT_S):
        self.model = model
        self.timeout = timeout

    def transcribe_page(self, image: Path, prompt: str) -> str:
        cli = _require("codex")
        full = f"Read the image file at {image}, then do the following.\n\n{prompt}"
        cmd = [cli, "exec", full]
        if self.model:
            cmd += ["--model", self.model]
        return _run(cmd, self.timeout, "codex")


class LlmEngine:
    name = "llm"

    def __init__(self, model: str | None = None, timeout: int = DEFAULT_TIMEOUT_S):
        self.model = model
        self.timeout = timeout

    def transcribe_page(self, image: Path, prompt: str) -> str:
        cli = _require("llm")
        cmd = [cli]
        if self.model:
            cmd += ["-m", self.model]
        cmd += ["-a", str(image), prompt]
        return _run(cmd, self.timeout, "llm")


_ENGINES = {"claude": ClaudeEngine, "codex": CodexEngine, "llm": LlmEngine}


def get_engine(name: str, model: str | None = None) -> Engine:
    try:
        factory = _ENGINES[name]
    except KeyError as exc:
        raise V2DError(
            f"unknown engine {name!r}; choose one of: {', '.join(_ENGINES)}"
        ) from exc
    return factory(model=model)
