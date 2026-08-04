# Bug Radar

A self-hosted bug bounty program radar — track public programs across
HackerOne, Bugcrowd and YesWeHack in one place. Live data, filters, and a
"new targets" feed, with zero API keys required.

Inspired by sites like bbradar.io, built to be yours: free to host, free to
extend, no accounts, no paywall.

## What it does

- Collects **587+ live programs** (HackerOne, Bugcrowd, YesWeHack public APIs)
- Shows bounty ranges, tags, platform, freshness ("added X ago") and an
  opportunity tier (Elite / Hot / Strong / Potential)
- Filters by platform, tag, search, VDP-only, and "new since last sweep"
- Grid / list views, sorting, pagination, detail modal with the program's
  policy snippet
- Tracks a **new targets feed** — programs that appeared since the previous
  collection run

## Project layout

```
bug-bounty-radar/
├── index.html          # the site — single self-contained file
├── collect.py          # fetches the 3 public APIs → data/*.json
├── data/
│   ├── programs.json       # all programs (normalized)
│   ├── latest-targets.json # programs new since last run
│   ├── meta.json           # stats + collection timestamp
│   └── state.json          # previous snapshot (diff source, internal)
└── .github/workflows/refresh.yml  # optional: daily auto-refresh
```

## Quick start

```bash
# 1. fetch fresh data (Python 3.10+)
python collect.py

# 2. serve the folder
python -m http.server 8000

# 3. open it
# http://localhost:8000
```

That's it. No dependencies, no API keys, no installs.

## Deploying (free)

### Option A — GitHub Pages (recommended)

1. Create a repo and push this folder.
2. The included workflow `.github/workflows/refresh.yml` re-runs
   `collect.py` every 6 hours and commits fresh `data/` — so the site stays
   live without you touching anything.
3. In repo Settings → Pages → deploy from `main` branch (root).

Your radar is then at `https://<you>.github.io/<repo>/`.

### Option B — any static host (Netlify, Vercel, Cloudflare Pages, S3…)

Push the folder; the site reads `data/*.json` at load time. Re-run
`collect.py` on a schedule (cron, GitHub Actions, CI) and redeploy to refresh.

### Option C — a small VPS / local server

Same as Quick start; point cron at `python collect.py` every few hours.

## Data sources

| Platform  | Endpoint used                          | Programs | Bounties  |
|-----------|----------------------------------------|----------|-----------|
| HackerOne | `/programs/search?query=bug_bounty`    | ~283     | parsed from policy text (best-effort) |
| Bugcrowd  | `/engagements.json`                    | ~243     | native min/max |
| YesWeHack | `api.yeswehack.com/programs`           | ~61      | native min/max |

All are public, unauthenticated endpoints. Bounties are USD where the source
exposes them; HackerOne amounts are extracted from the public policy text and
are best-effort (many programs publish amounts only in scope tables — those
show as "no public bounty", and the *hide VDP* toggle can be turned off to see
them).

## Customizing

- **Add a platform**: write a `fetch_*()` function in `collect.py` returning
  the normalized shape (`id`, `platform`, `name`, `url`, `about`, `policy`,
  `logo`, `tags`, `bounty_min`, `bounty_max`, `reports_count`, `status`),
  add it to `PLATFORMS`, re-run.
- **Tag rules**: extend `TAG_RULES` in `collect.py`.
- **Tiers**: tweak `tierOf()` in `index.html`.
- **Branding**: it's one HTML file — rename the header, colors are CSS
  variables at the top of `<style>`.

## Notes / limitations

- Public HackerOne search only returns a fraction of all programs (the full
  directory requires auth). Data is refreshed by re-running `collect.py`.
- `state.json` is what powers the "new targets" diff — commit it alongside
  `data/` when deploying so the feed persists across runs.
- Be a good citizen: the collector is polite (small delays between pages);
  don't hammer these endpoints.

## License

MIT — do whatever you want with it.
