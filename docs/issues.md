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
