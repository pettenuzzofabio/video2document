# Real-run issues log

Findings from running the pipeline on real recordings (PLAN.md milestone M5).

## 2026-07-20 — "DE Architecture Diagrams" (11 pages, EN, 5 diagrams)

Full `v2d run` produced a faithful `reconstructed.md`: title page, a Table of Contents
(as a Markdown table), the full heading hierarchy, nested bullet/number lists, footnote
markers, and the 5 architecture diagrams embedded as cropped assets with rich captions.
**Anti-hallucination held**: unreadable diagram-internal labels were flagged `[unclear]`,
not invented (7 unclear spans, all about tiny in-diagram text).

- **[FIXED] Orphan `FIGURE:` placeholder leaked into the output.** The model used the
  `](FIGURE:figN)` placeholder syntax for a plain link on a page that declared no such
  figure, leaving a broken `[text](FIGURE:figN)` in the markdown. Fixed: `transcribe` now
  strips any unresolved placeholder (keeps the visible text), running even for pages with
  zero declared figures.
- **[KNOWN] Boundary p10→p11 not healed.** A numbered list continued from p10 to p11, but
  only p11 set `continues_from_prev` (p10 didn't set `continues_to_next`); healing requires
  both flags (conservative, to avoid wrong merges). No content lost — cosmetically two blocks.
- **[BY DESIGN] Classification banners re-inserted into the body.** "Document classification:
  INTERNAL…" appeared on only 2/11 pages (< 60%), so it was treated as one-off and re-inserted
  rather than suppressed. Content-preserving but slightly noisy. Tunable via the 60% threshold.
- **[SOURCE LIMIT] Small diagram-internal labels illegible.** The 1296×1076 capture makes tiny
  in-diagram text low-resolution; correctly flagged `[unclear]`. Mitigation: record at higher
  resolution, or the planned v2 zoom-in feature.
- **[OK] No diagram clipping.** The full-page application-architecture diagram was captured
  completely by the auto-detected viewport.

**Confidentiality:** this document is marked INTERNAL/CONFIDENTIAL and its page images were
sent to the Claude API during transcription (expected for the `claude` engine). For
confidential material, use an offline engine (planned v2 `llama.cpp` adapter) or accept the
API exposure deliberately.

## 2026-07-20 — scroll stitching (`pages --mode scroll`, EXPERIMENTAL)

First cut of continuous-scroll stitching: a translation mosaic — template-match consecutive
cropped frames, accumulate offsets, break into a new segment (page) when the match fails.

Findings on the zoomed recording (49.5s, whitespace-heavy architecture doc):
- **Works on dense/textured content** with good overlap: correct tall/wide mosaics (e.g. 9
  frames → one 1915×1397 page; horizontal panning handled by the 2D offset).
- **Not yet reliable on this document overall**, two root causes:
  - `mpdecimate` thins frames by *content change*, so kept frames often jump more than the
    matcher's ~30%-of-frame range → breaks. Scroll mode wants many closely-spaced frames
    (`--no-decimate`) — but that alone over-segmented too (see below).
  - **Whitespace-heavy pages** are the core issue: a near-blank central patch gives the matcher
    nothing to lock onto → either mis-alignment **ghosts** (texture guard off) or **over-
    segmentation** (guard on). 66 frames → 26 pages (ghosts) or 43 pages (clean but fragmented).

Roadmap to make it robust (real CV iteration):
1. Confidence-weighted placement with **carry-forward** (reuse last good velocity across
   low-confidence/blank frames instead of breaking).
2. **Phase correlation** (whole-frame, sub-pixel) as primary estimator; blend overlaps to kill seams.
3. Genuine **page-break detection** (large discontinuity / full-width whitespace band).
4. Auto-use `--no-decimate` for scroll mode (record the decimate setting in meta).

Shipped behind the opt-in `--mode scroll`; default `pagefit` behaviour is unchanged.
