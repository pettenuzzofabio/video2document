# Decision log

One line per decision that isn't obvious from the code or that deviates from `PLAN.md`.
Newest first.

## M2 — pages (2026-07-20)

- **Viewport by temporal variance**: sample frames → per-pixel stddev over a downscaled
  stack → Otsu + morphology → largest-component bbox, padded. `--viewport x,y,w,h`
  override; always writes `viewport_preview.png` to eyeball; full-frame fallback (loud
  warning) if detection degenerates.
- **Anchored runs, not pairwise**: a frame joins a run while it stays pHash-similar to
  the run's *anchor* (first frame), so a slow scroll breaks the run instead of chaining
  — this is what makes "no stable run ⇒ continuous scroll" a reliable fail-loud signal.
- **Persistence classifies pages**: a run held ≥ `--min-page-ms` (default 400) is a page,
  read from pts-gap duration — robust to mpdecimate collapsing a dwell to one frame.
- **Revisit merge**: page runs with look-alike best frames collapse (back-scroll); pages
  ordered by first appearance. Known limit: genuinely identical pages merge into one.
- **SSIM merge pass deferred** (no scikit-image): pHash + persistence suffice on the
  fixtures; `--ssim` is accepted but reserved. Revisit if pHash proves noisy on real video.
- **Best frame** = max Laplacian variance, ties toward mid-run (screen recordings have no
  motion blur, so this mostly just rejects the rare mid-render frame).

## M1 — extract (2026-07-20)

- **Hybrid ffmpeg resolution** (`tools.ffmpeg_path`): prefer system ffmpeg, else the
  binary bundled in `imageio-ffmpeg`. Zero-install and reproducible, uses system tools
  (incl. ffprobe) when present. Runtime speed is identical (same engine).
- **`mpdecimate` ON by default** (`--no-decimate` to disable): big disk saving on
  mostly-static screen recordings. Consequence: each stable dwell collapses to one
  frame, so **dwell duration is encoded in pts gaps** (large gap ⇒ page, ~1-frame gap
  ⇒ transition). M2 must classify pages via persistence, not cluster size.
- **Accurate timestamps via `showinfo`** parsed from stderr, not filename arithmetic.
- **No hashing in `extract`**: mpdecimate handles exact-duplicate dropping at decode;
  authoritative pHash/sharpness are computed in `pages` on cropped frames.
- **Metadata via ffprobe if present, else imageio** → normalized `source.meta.json`
  (raw ffprobe also dumped to `source.ffprobe.json`). opencv deferred to M2.
- **Source video symlinked** into `input/` for provenance, never copied (no GB dupes).

## M0 — scaffolding (2026-07-20)

- **CLI framework: typer.** Clean subcommand ergonomics and `--help` for a CLI that
  will grow; the `click` dependency it pulls in is standard and stable.
- **Dependencies added incrementally, not all upfront.** M0 runtime dep is just
  `typer`; the heavy CV stack (opencv, scikit-image, imagehash, numpy, Pillow) is
  added when its milestone (M1/M2) actually uses it, keeping the M0 env small.
- **Fixture generator is pure-Python (Pillow + `imageio-ffmpeg`).** System ffmpeg,
  poppler, and pandoc need `sudo apt-get` (no passwordless sudo here), so synthetic
  fixtures use the ffmpeg binary bundled in `imageio-ffmpeg` and need no system tools.
  Synthetic fixtures are deterministic test stand-ins, **not** a replacement for real
  screen recordings (see `fixtures/README.md`).
- **Ground truth for synthetic fixtures is the authored text** (written to
  `*.pages.json`), which is exact — better than a `pdftotext` proxy. Real recordings
  still rely on their source PDF as ground truth.
- **Git author identity: repo-local**, name "Fabio Pettenuzzo", email
  `pettenuzzofabio@users.noreply.github.com` (GitHub noreply — keeps the real address
  out of public history). Global git config was unset; set only for this repo. Trivially
  changeable while history is short (`git commit --amend --reset-author`).
- **No project license file yet** — left to the owner to choose.
