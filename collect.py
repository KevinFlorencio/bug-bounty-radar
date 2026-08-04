#!/usr/bin/env python3
"""
Bug Bounty Radar — data collector.

Fetches public program listings from HackerOne, Bugcrowd and YesWeHack
(no auth needed) and normalizes them into data/programs.json plus
data/latest-targets.json (programs newly seen since the last run).

Usage:
    python collect.py            # fetch + normalize + write data/
    python collect.py --quiet    # no progress output

Outputs:
    data/programs.json          every program, normalized
    data/latest-targets.json    new programs since last run (the "radar" feed)
    data/state.json             previous snapshot + run timestamps (internal)

All timestamps are UTC ISO-8601. Bounties are parsed into USD integers when
the source exposes them; otherwise null (VDP / unknown).
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROGRAMS_PATH = os.path.join(DATA_DIR, "programs.json")
TARGETS_PATH = os.path.join(DATA_DIR, "latest-targets.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 30

PLATFORMS = ["HackerOne", "Bugcrowd", "YesWeHack"]


def log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def http_get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def http_get_json(url: str, headers: dict | None = None):
    h = {"Accept": "application/json", **(headers or {})}
    return json.loads(http_get(url, h).decode("utf-8"))


# ---------------------------------------------------------------------------
# Bounty parsing helpers
# ---------------------------------------------------------------------------

DOLLAR_RE = re.compile(
    r"\$\s*([\d,]+(?:\.[\d]+)?)\s*(?:-|–|—|to|up to)\s*\$\s*([\d,]+(?:\.[\d]+)?)",
    re.IGNORECASE,
)
SINGLE_RE = re.compile(r"\$\s*([\d,]+(?:\.[\d]+)?)", re.IGNORECASE)
TRAILING_RE = re.compile(r"([\d]+(?:,[\d]{3})*(?:\.[\d]+)?)\s*\$", re.IGNORECASE)


def parse_bounty_range(text: str | None) -> tuple[int | None, int | None]:
    """Best-effort USD range extraction from free text. Returns (min, max)."""
    if not text:
        return None, None
    m = DOLLAR_RE.search(text)
    if m:
        lo = int(float(m.group(1).replace(",", "")))
        hi = int(float(m.group(2).replace(",", "")))
        if hi >= lo:
            return lo, hi
    # single "$X" or trailing "X$" -> treat as max (e.g. "up to $10,000", "500$")
    nums = [int(float(x.replace(",", ""))) for x in SINGLE_RE.findall(text)]
    nums += [int(float(x.replace(",", ""))) for x in TRAILING_RE.findall(text)]
    nums = [n for n in nums if n >= 10]  # filter noise (e.g. $5 gift cards)
    if nums:
        return None, max(nums)
    return None, None


def clean_policy(text: str | None, limit: int = 4000) -> str:
    """Tidy H1-style markdown policy into readable plain text."""
    if not text:
        return ""
    t = html.unescape(text)
    # drop image embeds and bare URLs (noise for a text preview)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)          # ![alt](url)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)        # [label](url) -> label
    t = re.sub(r"https?://\S+", "", t)                    # bare urls
    t = re.sub(r"[ \t]+", " ", t)                        # collapse whitespace
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"^\s+", "", t, flags=re.M)
    t = re.sub(r"^[#>*\-]\s*", "", t, flags=re.M)        # markdown bullets/headers
    t = re.sub(r"&nbsp;?", " ", t)
    t = t.replace("\xa0", " ")
    return t.strip()[:limit]


# ---------------------------------------------------------------------------
# Tag classification (HackerOne search results have no tags; classify from text)
# ---------------------------------------------------------------------------

TAG_RULES = [
    ("mobile", ["mobile", "android", "ios", "iphone", "ipad"]),
    ("web", ["web", "website", "xss", "csrf", "owasp", "web app", "browser"]),
    ("api", ["api", "graphql", "rest", "endpoint", "webhook"]),
    ("smart contract", ["smart contract", "solidity", "defi", "evm", "audit"]),
    ("blockchain", ["blockchain", "chain", "crypto", "wallet", "token", "web3", "nft"]),
    ("source code", ["source code", "source-code", "repository", "github", "code review", "static analysis"]),
    ("infrastructure", ["infrastructure", "kubernetes", "docker", "cloud", "aws", "gcp", "azure", "server"]),
    ("hardware", ["hardware", "firmware", "iot", "embedded"]),
    ("desktop", ["desktop", "windows application", "macos", "linux application", "electron"]),
    ("ai/ml", ["ai", "llm", "machine learning", "ml model", "chatbot", "prompt"]),
]


def classify_tags(*texts: str | None) -> list[str]:
    blob = " ".join(t.lower() for t in texts if t)
    tags = [name for name, kws in TAG_RULES if any(k in blob for k in kws)]
    return tags


# ---------------------------------------------------------------------------
# Source 1: HackerOne
# ---------------------------------------------------------------------------

H1_SEARCH = (
    "https://hackerone.com/programs/search"
    "?query=bug_bounty&sort=published_at:descending&page={page}"
)


def fetch_hackerone(quiet: bool) -> list[dict]:
    programs = []
    page = 1
    while True:
        data = http_get_json(H1_SEARCH.format(page=page))
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            if r.get("team_type") not in ("external_program", "team"):
                continue
            about = r.get("about") or ""
            policy = r.get("stripped_policy") or ""
            lo, hi = parse_bounty_range(policy)
            programs.append(
                {
                    "id": f"hackerone:{r['handle']}",
                    "platform": "HackerOne",
                    "name": r.get("name") or r.get("handle"),
                    "handle": r.get("handle"),
                    "url": "https://hackerone.com" + r.get("url", ""),
                    "about": clean_policy(about, 600),
                    "policy": clean_policy(policy),
                    "logo": r.get("profile_picture"),
                    "tags": classify_tags(about, policy, r.get("name")),
                    "bounty_min": lo,
                    "bounty_max": hi,
                    "reports_count": None,
                    "status": "active",
                }
            )
        log(f"  HackerOne page {page}: {len(results)} rows", quiet)
        total = data.get("total", 0)
        if page * data.get("limit", 100) >= total:
            break
        page += 1
        time.sleep(0.3)
    log(f"HackerOne: {len(programs)} programs", quiet)
    return programs


# ---------------------------------------------------------------------------
# Source 2: Bugcrowd
# ---------------------------------------------------------------------------

BC_URL = "https://bugcrowd.com/engagements.json?page={page}"


def _bc_money(s: str | None) -> int | None:
    if not s:
        return None
    n = re.sub(r"[^\d]", "", s)
    return int(n) if n else None


def fetch_bugcrowd(quiet: bool) -> list[dict]:
    programs = []
    page = 1
    while True:
        data = http_get_json(BC_URL.format(page=page))
        rows = data.get("engagements", [])
        if not rows:
            break
        for e in rows:
            if e.get("productEngagementType", {}).get("label") != "Bug Bounty":
                continue
            if e.get("isPrivate") or e.get("isDemo"):
                continue
            rs = e.get("rewardSummary") or {}
            tags = classify_tags(e.get("tagline"), e.get("name"), e.get("industryName"))
            industry = e.get("industryName")
            if industry and industry not in tags and industry.lower() != "other":
                tags = tags + [industry.lower()] if industry.lower() not in tags else tags
            programs.append(
                {
                    "id": f"bugcrowd:{e['briefUrl'].rsplit('/', 1)[-1]}",
                    "platform": "Bugcrowd",
                    "name": e.get("name"),
                    "handle": e.get("briefUrl", "").rsplit("/", 1)[-1],
                    "url": e.get("briefUrl"),
                    "about": (e.get("tagline") or "").strip(),
                    "policy": "",
                    "logo": e.get("logoUrl"),
                    "tags": tags,
                    "bounty_min": _bc_money(rs.get("minReward")),
                    "bounty_max": _bc_money(rs.get("maxReward")),
                    "reports_count": None,
                    "status": "active" if e.get("accessStatus") == "open" else (e.get("accessStatus") or "unknown"),
                }
            )
        log(f"  Bugcrowd page {page}: {len(rows)} rows", quiet)
        meta = data.get("paginationMeta", {})
        if page * meta.get("limit", 24) >= meta.get("totalCount", 0):
            break
        page += 1
        time.sleep(0.3)
    log(f"Bugcrowd: {len(programs)} programs", quiet)
    return programs


# ---------------------------------------------------------------------------
# Source 3: YesWeHack
# ---------------------------------------------------------------------------

YWH_URL = "https://api.yeswehack.com/programs?page={page}"


def fetch_yeswehack(quiet: bool) -> list[dict]:
    programs = []
    page = 1
    while True:
        data = http_get_json(YWH_URL.format(page=page))
        rows = data.get("items", [])
        if not rows:
            break
        for it in rows:
            if not it.get("public") or it.get("archived") or it.get("disabled"):
                continue
            if it.get("type") != "bug-bounty":
                continue
            lo = it.get("bounty_reward_min")
            hi = it.get("bounty_reward_max")
            tags = classify_tags(it.get("title"), it.get("activity_area"))
            area = it.get("activity_area")
            if area and area.lower() != "tech - other" and "tech" not in area.lower():
                tags.append(area.split(" - ")[0].lower())
            programs.append(
                {
                    "id": f"yeswehack:{it['slug']}",
                    "platform": "YesWeHack",
                    "name": it.get("title"),
                    "handle": it.get("slug"),
                    "url": f"https://yeswehack.com/programs/{it.get('slug')}",
                    "about": "",
                    "policy": "",
                    "logo": it.get("thumbnail"),
                    "tags": tags,
                    "bounty_min": lo,
                    "bounty_max": hi,
                    "reports_count": it.get("reports_count"),
                    "status": "active" if it.get("status") == "V" else (it.get("status") or "unknown"),
                }
            )
        log(f"  YesWeHack page {page}: {len(rows)} rows", quiet)
        pag = data.get("pagination", {})
        if page >= pag.get("nb_pages", 1):
            break
        page += 1
        time.sleep(0.3)
    log(f"YesWeHack: {len(programs)} programs", quiet)
    return programs


# ---------------------------------------------------------------------------
# Snapshot diff -> latest targets
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"previous": {}, "last_run": None}


def save_state(state: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def build_latest_targets(programs: list[dict], prev: dict, now: datetime) -> list[dict]:
    """Programs whose id was not present in the previous snapshot = new targets."""
    prev_ids = set(prev.keys())
    fresh = []
    for p in programs:
        if p["id"] not in prev_ids:
            fresh.append(
                {
                    "id": p["id"],
                    "platform": p["platform"],
                    "name": p["name"],
                    "url": p["url"],
                    "tags": p["tags"],
                    "bounty_max": p["bounty_max"],
                    "first_seen": now.isoformat(),
                }
            )
    # newest first
    return sorted(fresh, key=lambda x: x["first_seen"], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Bug Bounty Radar collector")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--platforms", default=",".join(PLATFORMS),
                        help="comma-separated platforms: HackerOne,Bugcrowd,YesWeHack")
    args = parser.parse_args()

    wanted = {p.strip() for p in args.platforms.split(",") if p.strip()}
    now = datetime.now(timezone.utc)
    all_programs: list[dict] = []

    for platform in PLATFORMS:
        if platform not in wanted:
            continue
        try:
            if platform == "HackerOne":
                all_programs.extend(fetch_hackerone(args.quiet))
            elif platform == "Bugcrowd":
                all_programs.extend(fetch_bugcrowd(args.quiet))
            elif platform == "YesWeHack":
                all_programs.extend(fetch_yeswehack(args.quiet))
        except Exception as exc:
            log(f"  !! {platform} failed: {exc}", quiet=args.quiet)

    # dedupe by id (keep first)
    seen: dict[str, dict] = {}
    for p in all_programs:
        seen.setdefault(p["id"], p)
    programs = list(seen.values())

    # preserve source fetch order (H1 search is newest-first) as a sort key
    for i, p in enumerate(programs):
        p["seq"] = i

    state = load_state()
    targets = build_latest_targets(programs, state.get("previous", {}), now)

    # per-program first_seen (persisted across runs) for freshness displays
    prev = state.get("previous", {})
    for p in programs:
        p["first_seen"] = prev.get(p["id"], {}).get("first_seen") or now.isoformat()
    state["previous"] = {
        p["id"]: {"platform": p["platform"], "name": p["name"], "first_seen": p["first_seen"]}
        for p in programs
    }
    state["last_run"] = now.isoformat()

    os.makedirs(DATA_DIR, exist_ok=True)

    # programs.json: array of all programs (stable order by platform then name)
    programs.sort(key=lambda p: (p["platform"], p["name"].lower()))
    with open(PROGRAMS_PATH, "w", encoding="utf-8") as f:
        json.dump(programs, f, ensure_ascii=False, indent=1)

    with open(TARGETS_PATH, "w", encoding="utf-8") as f:
        json.dump(targets, f, ensure_ascii=False, indent=1)

    by_platform: dict[str, int] = {}
    for p in programs:
        by_platform[p["platform"]] = by_platform.get(p["platform"], 0) + 1

    with_bounty = [p for p in programs if p["bounty_max"]]

    with open(os.path.join(DATA_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "collected_at": now.isoformat(),
                "programs_total": len(programs),
                "programs_with_bounty": len(with_bounty),
                "new_targets": len(targets),
                "platforms": sorted({p["platform"] for p in programs}),
                "platform_counts": by_platform,
            },
            f,
            ensure_ascii=False,
            indent=1,
        )

    save_state(state)

    log(f"DONE: {len(programs)} programs total ({len(with_bounty)} with bounty), "
        f"{len(targets)} new targets since last run", quiet=args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
