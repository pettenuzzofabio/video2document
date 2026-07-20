# Test fixtures

Two kinds of fixture, for two purposes.

## 1. Synthetic fixtures (deterministic, committed generator)

`scripts/make_fixtures.py` renders short MP4s of a fake document viewer paging through
a few pages, plus a ground-truth JSON per video. They are **deterministic** and need no
system tools (Pillow renders the pages; the ffmpeg bundled in `imageio-ffmpeg` encodes),
so they are the fixtures the automated pipeline tests run against.

```bash
uv run python scripts/make_fixtures.py            # all fixtures -> fixtures/generated/
uv run python scripts/make_fixtures.py --only it_table_chart
uv run python scripts/make_fixtures.py --dump-sample   # also drop a sample frame PNG
```

Output (git-ignored — regenerate any time):

```
fixtures/generated/
  en_simple.mp4          en_simple.pages.json
  it_table_chart.mp4     it_table_chart.pages.json
  en_backscroll.mp4      en_backscroll.pages.json
```

The three cover the cases the plan's acceptance tests need:

| Fixture | Language | Exercises |
|---|---|---|
| `en_simple` | English | baseline: 3 text pages, linear order |
| `it_table_chart` | Italian | a Markdown table + a chart-as-figure; accents |
| `en_backscroll` | English | view order `[1,2,3,2,1]` — the **revisit merge** (M2) |

Each `*.pages.json` records the distinct pages, their authored text (exact ground
truth for accuracy checks), the viewing order, and the expected distinct-page count.

**Limitation:** synthetic pages are clean renders — no compression noise, no real
browser chrome, no motion blur. They validate the geometry and assembly logic but are
not a substitute for real recordings when judging real-world OCR/LLM quality.

## 2. Real recordings (manual, not committed)

Record 2–3 short screen recordings yourself following the **Recording guidelines** in
the top-level `README.md` (fit-page single-page view, PgDn paging, cursor in the margin).
Keep the **source PDF** next to each recording — it is free ground truth for accuracy.
At least one recording should include a **back-scroll** (revisiting an earlier page).

Store these outside git (they are large binaries) — e.g. under `~/v2d-work/fixtures/` —
and note here where they live and how each was produced.
