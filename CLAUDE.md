# Bug Radar — project context for Claude Code / Fable

Self-hosted bug bounty program radar. Tracks live public programs from
HackerOne, Bugcrowd and YesWeHack. Inspired by bbradar.io.

## Layout

- `index.html` — the ENTIRE frontend, single self-contained file (embedded
  CSS + JS, no build step). This is what you will redesign.
- `collect.py` — data collector (fetches the 3 public APIs → `data/*.json`).
- `data/programs.json` — all programs (normalized array; ~587 entries).
- `data/latest-targets.json` — programs new since last collector run.
- `data/meta.json` — stats + collection timestamp.
- `data/state.json` — internal diff state; do not edit.
- `.github/workflows/refresh.yml` — daily data refresh (GitHub Actions).
- Site is deployed to GitHub Pages from `main`; `data/` is auto-committed by
  the refresh workflow — only `index.html` (and `collect.py` if asked) are
  human-edited.

## Redesign constraints (IMPORTANT)

1. **Keep the data layer untouched.** The frontend fetches
   `data/programs.json`, `data/latest-targets.json`, `data/meta.json` at load
   time. Do not rename fields, change the fetch paths, or modify collect.py
   unless explicitly asked.
2. **Keep every existing feature working:** stats bar (4 cells), "new
   targets" ticker, search box, sort dropdown, grid/list toggle, hide-VDP
   toggle, new-only toggle, platform chips, tag chips, result count + page
   indicator, pagination (25/page), and the program detail modal (bounty,
   opportunity tier, tags, policy snippet, "Open program" link).
3. Keep the current single-file architecture (no build step, no framework,
   no external JS deps). Google Fonts + the inline SVG favicon are fine.
4. The site must keep working when opened via `python -m http.server` and on
   GitHub Pages (relative paths only).
5. Reuse the existing CSS custom properties where sensible; a full visual
   redesign is welcome, but keep the dark, security/radar aesthetic and the
   green/cyan accent language unless the user asks for something else.
6. Bounty display logic (`bountyHtml`, `fmtMoney`, `tierOf`), the `esc()`
   escaping helpers, and the `[object Object]`-proof `avatarHtml` guard must
   stay intact.
7. Verify the result in a browser (e.g. `python -m http.server` + screenshot
   or DOM check) before declaring done.

## Bounty tier thresholds (used by tierOf)

- Elite ≥ $100k · Hot ≥ $25k · Strong ≥ $5k · Potential ≥ $500 · else none.

## Quick checks

- Serve: `python -m http.server 8000` → http://localhost:8000
- Refresh data: `python collect.py --quiet`
