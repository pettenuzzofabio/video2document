# video2document

Reconstruct a document from a **screen recording of someone scrolling through it**.

The pipeline extracts frames from the video, isolates one clean image per page,
transcribes each page with a vision-capable CLI LLM, and assembles a semantically
complete Markdown document (with tables preserved and figures/charts embedded as
cropped images), plus an optional rendered PDF.

See [`PLAN.md`](PLAN.md) for the full architecture, milestones, and design rationale,
and [`deep-research.md`](deep-research.md) for the underlying research.

> **Status: M0 — scaffolding.** The CLI surface and workspace contract exist; every
> stage is a stub. Implementation lands milestone by milestone (M1 = `extract`, …).

## How it works

Five staged subcommands, connected by an on-disk *workspace* so each stage is
independently runnable, inspectable, and resumable:

| Stage | Command | Does | Milestone |
|---|---|---|---|
| 1 | `v2d extract` | decode the video → frames + frame manifest | M1 |
| 2 | `v2d pages` | frames → one clean image per page | M2 |
| 3 | `v2d transcribe` | page images → per-page Markdown + JSON sidecar | M3 |
| 4 | `v2d assemble` | per-page Markdown → `reconstructed.md` (+ optional PDF) | M4 |
| — | `v2d run` | the whole chain, extract → assemble | — |

## Scope (v1)

Clean **screen recordings** of **page-fit** scrolling (each page fully visible at
some moment), documents in **Italian or English**, transcribed **LLM-vision-first**
(Claude Code by default). Camera-filmed input, continuous-scroll stitching, zoomed-in
charts, and a classical-OCR cross-check are explicitly deferred to v2 — see `PLAN.md`.

## Requirements

- **Python ≥ 3.12** and [**uv**](https://docs.astral.sh/uv/).
- **ffmpeg / ffprobe** — frame extraction (M1). Ubuntu/WSL: `sudo apt-get install ffmpeg`.
- **Claude Code CLI** (`claude`) — default transcription engine (M3).
- **pandoc** — only for `v2d assemble --pdf` (M5). Ubuntu/WSL: `sudo apt-get install pandoc`.

The dev/test tooling (fixture generator) bundles its own ffmpeg via `imageio-ffmpeg`,
so tests do not require system ffmpeg.

## Install

```bash
uv sync            # runtime deps + dev group into .venv
uv run v2d --help
```

## Usage

```bash
# whole pipeline
uv run v2d run recording.mp4 --workdir ~/v2d-work/mydoc --pdf

# or stage by stage (each re-runnable and resumable)
uv run v2d extract recording.mp4 --workdir ~/v2d-work/mydoc --fps 6
uv run v2d pages      --workdir ~/v2d-work/mydoc
uv run v2d transcribe --workdir ~/v2d-work/mydoc --engine claude
uv run v2d assemble   --workdir ~/v2d-work/mydoc --pdf
```

**Tip (WSL):** keep `--workdir` on the Linux filesystem (e.g. `~/v2d-work/...`), not on
`/mnt/c`, because frame extraction is I/O-heavy and the Windows mount is slow.

## Recording guidelines

Capture quality is the ceiling — no pipeline recovers pixels that were never captured.
When you can export the document directly (Save as PDF, print-to-PDF), do that instead.
When a video is the only option:

- Record at native resolution; the page should be **≥ 1000 px wide** in the video.
- Viewer in **fit-page, single-page** view; page with **PgDn/PgUp** (no smooth scroll).
- Pause ~1 second per page; keep the cursor parked in a margin, never over text.
- Disable notifications/overlays; keep zoom constant throughout.

## Development

```bash
uv run pytest                            # tests
uv run python scripts/make_fixtures.py   # generate synthetic test videos (see fixtures/)
```

Project layout:

```
src/video2document/
  cli.py            # the `v2d` command (typer)
  workspace.py      # the on-disk workspace contract
  exceptions.py
  stages/           # extract / pages / transcribe / assemble
tests/
scripts/make_fixtures.py
fixtures/           # how to make test videos (real + synthetic)
```
