# Decision log

One line per decision that isn't obvious from the code or that deviates from `PLAN.md`.
Newest first.

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
