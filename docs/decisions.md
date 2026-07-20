# Decision log

One line per decision that isn't obvious from the code or that deviates from `PLAN.md`.
Newest first.

## M5/M6 — close-out (2026-07-20)

- **`--pdf` works without sudo**: pandoc if on PATH (best quality), else a pure-pip fallback
  (`markdown` → HTML → `xhtml2pdf`, no system libraries). Validated: 11-page PDF, 6 embedded
  diagram images, full text incl. the extracted hi-res diagram data.
- **opencv-python → opencv-python-headless**: the pipeline never opens GUI windows, and the
  headless wheel imports on bare servers/CI (no `libGL`). Drop-in swap.
- **CI**: GitHub Actions runs `uv sync && pytest` on push/PR — needs no claude/ffmpeg/poppler
  (claude is stubbed in tests, ffmpeg is the bundled imageio-ffmpeg binary).
- **M5 closed** (PDF + LLM merge pass + real-video run/issues log all done). **M6**: `--verbose`
  done, engine seam proven, CI added; a per-workdir config file was deliberately **skipped**
  (CLI flags already cover tuning — avoid over-engineering).

## v2 (started) — hi-res diagram supplements + rotation (2026-07-20)

- **`v2d details`**: for dense diagrams illegible in the video, the user drops hi-res photos
  in `<workdir>/details/`. Each is matched to its page by **ORB features + homography RANSAC**
  (deterministic, no LLM), embedded on that page, and one LLM pass extracts its data into the
  page Markdown. Only matched pages are touched (`detail_images` in pages.jsonl). Standalone
  stage, run between transcribe and assemble. Validated on the real doc: the high-res AS-IS
  diagram matched page 3 (339 inliers) and its previously-`[unclear]` labels were fully extracted.
- **`pages --rotate {none,cw,ccw,180}`** brings rotated pages upright (PDFs rendered rotated to
  fill a landscape screen); with `none`, a projection-profile heuristic *warns* if pages look
  rotated 90° (never auto-rotates — cw/ccw is ambiguous). The two real recordings tested upright.

## v2 (started) — scroll stitching (2026-07-20)

- **`pages --mode scroll`** (opt-in; default stays `pagefit`): a translation-only mosaic
  (`stitching.py`) that template-matches consecutive cropped frames, accumulates 2D offsets,
  and breaks into a new page when the match fails. Reuses viewport+crop; emits the same
  `pages/*.png` + `pages.jsonl` contract, so transcribe/assemble are unchanged.
- **Experimental**: works on dense/textured content, unreliable on whitespace-heavy pages
  (ghosts vs over-segmentation). Findings + roadmap in `docs/issues.md`. Not promoted to a
  default; needs confidence-weighted carry-forward, phase correlation, and blending to be robust.
- **Scroll wants `--no-decimate`** at extract (mpdecimate thins by content change, which
  enlarges frame-to-frame jumps beyond the matcher's range).

## M4 — assemble + run (2026-07-20)

- **Block-based assembly**: pages split into blank-line-separated blocks; a boundary
  between `continues_to_next`/`continues_from_prev` pages merges the trailing block of one
  with the leading block of the next (handles chained continuations by popping the running tail).
- **Deterministic healing first** (de-hyphenate/join paragraphs; concatenate table rows,
  dropping a repeated header+separator). Optional `--merge-pass` refines only the boundary
  text via `engine.complete()` (text-only); engine is lazy and falls back to deterministic
  if unavailable. No boundaries ⇒ no LLM call.
- **Header/footer**: body already excludes them (M3 routes them to the sidecar). Assemble
  confirms *running* ones by digit-insensitive repetition (≥60% of pages) and keeps them out;
  one-off values are re-inserted into the body so a misclassified heading isn't lost.
- **Missing pages** get a visible placeholder in the doc + a report entry (never silently dropped).
- **PDF** via pandoc (subprocess, cwd=`out/` so `../assets/` resolves); clean error if pandoc
  or its PDF engine is absent — the Markdown is canonical.
- **`complete()` added to the Engine protocol** for text-only calls (the merge pass),
  separate from `transcribe_page()`.

## M3 — transcribe (2026-07-20)

- **`claude -p` validated headless** from inside a Claude Code session:
  `claude -p "Read the image at <abs> … " --allowedTools Read --output-format text`
  reads the image and returns clean text. Adapters: claude (validated), codex/llm (best-effort).
- **Sentinel-delimited output, not code fences** (`===V2D_MARKDOWN===` / `===V2D_JSON===`):
  a transcribed page can itself contain ``` fences. Defensive fence-strip on the JSON part.
- **jsonschema on the sidecar**, types (no strict enums) to avoid spurious retries on
  wording. One retry on malformed output, then keep raw as `.error.txt` and continue —
  a per-page failure doesn't kill the batch.
- **Figures**: the model emits `![cap](FIGURE:figN)` placeholders + a `figures[]` bbox_pct;
  the stage crops (+2% pad) into `assets/` and rewrites the placeholder. Bad/degenerate
  bbox → embed the full page. `../assets/...` resolves from both `llm/` and `out/`.
- **Pipeline page number enforced** (`sidecar["page"] = page_no`), not trusted from the model.
- **Anti-hallucination**: strict no-guess prompt + `[unclear: …]` + per-page isolation;
  the OCR cross-check (v2) is the fallback if real runs show invention.

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
