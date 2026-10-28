#!/usr/bin/env python3
"""Build an offline NotUltraNX game-ID/name index; no download links or tokens.

Default mode contacts only the public TitleDB metadata source. Optional
--scan-site mode reads public listing pages conservatively and stops on
rate-limiting instead of retrying or evading access restrictions.
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

TITLEDB = "https://raw.githubusercontent.com/blawar/titledb/master/US.en.json"
SITE = "https://not.ultranx.ru/en"
ID_PATTERN = re.compile(r"^[0-9A-F]{16}$")
SITE_ID_PATTERN = re.compile(r"/game/([0-9A-Fa-f]{16})(?![0-9A-Fa-f])")


def valid_id(value):
    return isinstance(value, str) and ID_PATTERN.fullmatch(value.upper()) is not None


def load_catalog(path):
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != 1 or not isinstance(document.get("games"), list):
        raise ValueError("Unexpected catalog schema in " + str(path))
    result = {}
    for row in document["games"]:
        if not isinstance(row, dict) or not valid_id(row.get("id")):
            continue
        id_ = row["id"].upper()
        result[id_] = {
            "id": id_,
            "name": str(row.get("name") or "")[:512],
            "cardText": str(row.get("cardText") or "")[:3400],
        }
    return result


def fetch(url, limit):
    request = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0" if url.startswith(SITE) else
                       "SwitchGamesBrowser-catalog-builder/1.0 (public metadata)"),
        "Accept": "application/json,text/html;q=0.8",
    })
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Metadata response exceeds expected size")
    return data


def listing_html(page, pages_dir=None):
    """Use cached browser-accessible pages, or read the public site directly."""
    if pages_dir is not None:
        file = pages_dir / f"notultranx-page-{page}.html"
        if not file.is_file():
            raise RuntimeError(f"Missing cached listing page {page}: {file}")
        return file.read_text(encoding="utf-8", errors="replace")
    url = SITE + "?p=" + str(page) + "&s=&sb=release_date&so=desc"
    return fetch(url, 4 * 1024 * 1024).decode("utf-8", "replace")


def listing_text(markup, match):
    """Small searchable snippet around a game card for titles absent in TitleDB."""
    from html import unescape
    left = max(0, match.start() - 160)
    right = min(len(markup), match.end() + 750)
    text = re.sub(r"<[^>]*>", " ", markup[left:right])
    text = unescape(text)
    return re.sub(r"[^a-z0-9]", "", text.lower())[:1800]


def listing_name(markup, match):
    """Read a linked title where available, rather than inventing a title."""
    from html import unescape
    anchor_start = markup.rfind("<a", max(0, match.start() - 900), match.start())
    anchor_end = markup.find("</a>", match.end(), min(len(markup), match.end() + 2500))
    if anchor_start < 0 or anchor_end < 0:
        return ""
    open_end = markup.find(">", match.end(), anchor_end)
    if open_end < 0:
        return ""
    inner = markup[open_end + 1:anchor_end]
    visible = unescape(re.sub(r"<[^>]*>", " ", inner)).strip()
    visible = " ".join(visible.split())
    if 4 <= len(visible) <= 180 and sum(c.isalpha() for c in visible) >= 4:
        return visible
    alt = re.search(r"""(?:alt|title)\s*=\s*['"]([^'"]+)['"]""", inner, re.I)
    if alt:
        visible = " ".join(unescape(alt.group(1)).split())
        if 4 <= len(visible) <= 180:
            return visible
    return ""


def merge_site_ids(games, max_pages, pages_dir=None):
    """Read all listing pages and merge every discovered ID.

    Never publish a partial scan as successful. A short final page signals
    the end; failed pages/empty responses abort without modifying the JSON.
    """
    discovered = {}
    first_page_size = None
    finished = False
    for page in range(1, max_pages + 1):
        markup = listing_html(page, pages_dir)
        matches = list(SITE_ID_PATTERN.finditer(markup))
        page_ids = {m.group(1).upper() for m in matches}
        if len(page_ids) < 1:
            raise RuntimeError(f"Listing page {page} had no game IDs; refusing partial scan")
        if first_page_size is None:
            first_page_size = len(page_ids)
            if first_page_size < 20:
                raise RuntimeError("First listing page unexpectedly small")
        new_on_page = 0
        for m in matches:
            id_ = m.group(1).upper()
            if id_ in discovered:
                continue
            discovered[id_] = {
                "id": id_,
                "name": listing_name(markup, m),
                "cardText": listing_text(markup, m),
            }
            new_on_page += 1
        print(f"Page {page}: {len(page_ids)} IDs, {new_on_page} new", flush=True)
        if page > 1 and new_on_page == 0:
            raise RuntimeError(f"Listing page {page} repeated prior IDs; aborting incomplete scan")
        if page > 1 and len(page_ids) < first_page_size:
            finished = True
            break
        if pages_dir is None:
            time.sleep(1.5)
    if not finished:
        raise RuntimeError(
            "No shorter final listing page found; refusing unverified catalog scan"
        )
    # A blocked or truncated listing may still return HTTP 200 and valid HTML.
    if len(discovered) < max(100, int(len(games) * 0.85)):
        raise RuntimeError(
            f"Only {len(discovered)} site IDs versus {len(games)} saved; "
            "refusing incomplete refresh"
        )
    added = 0
    for id_, fresh in discovered.items():
        previous = games.get(id_)
        if previous is None:
            if len(games) >= 10000:
                raise RuntimeError("Too many NotUltraNX catalog entries")
            games[id_] = fresh
            added += 1
        else:
            # Preserve established names and older metadata.
            if not previous["name"] and fresh["name"]:
                previous["name"] = fresh["name"]
            if not previous["cardText"] and fresh["cardText"]:
                previous["cardText"] = fresh["cardText"]
    print(
        f"Complete site scan: {len(discovered)} IDs, {added} added; "
        f"catalog now {len(games)} IDs",
        flush=True,
    )


def add_metadata(games, source):
    """TitleDB is keyed by Nintendo eShop ID; game objects contain title IDs."""
    print("Fetching public TitleDB names...", flush=True)
    payload = json.loads(fetch(source, 150 * 1024 * 1024))
    if not isinstance(payload, dict):
        raise ValueError("Unexpected TitleDB JSON structure")
    named = 0
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        id_ = row.get("id") or row.get("titleId")
        name = row.get("name")
        if not valid_id(id_) or not isinstance(name, str):
            continue
        name = name.strip()
        if not name or len(name) > 512:
            continue
        existing = games.get(id_.upper())
        if existing is not None and not existing["name"]:
            existing["name"] = name
            named += 1
    print(f"Named {named} additional catalog IDs", flush=True)


def game_page_name(markup):
    """Extract the visible heading from a game detail page, not nearby cards."""
    from html import unescape
    match = re.search(r"<h1\b[^>]*>(.*?)</h1\s*>", markup, re.I | re.S)
    if not match:
        return ""
    title = " ".join(unescape(re.sub(r"<[^>]*>", " ", match.group(1))).split())
    if not (4 <= len(title) <= 512 and sum(c.isalpha() for c in title) >= 4):
        return ""
    if title.lower() in {"notultranx", "not found", "access denied", "error"}:
        return ""
    return title


def enrich_missing_site_names(games, max_requests=200):
    """Resolve only unnamed IDs via their known NotUltraNX detail pages.

    TitleDB remains the first choice. Failures preserve blanks rather than
    making up names; stop on rate limiting instead of retrying or evading it.
    """
    missing = [id_ for id_, row in sorted(games.items()) if not row["name"]]
    named = 0
    for id_ in missing[:max_requests]:
        url = SITE + "/game/" + id_
        try:
            markup = fetch(url, 4 * 1024 * 1024).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                print(f"Game-page name lookup rate-limited (HTTP {exc.code}); stopping", flush=True)
                break
            print(f"Game-page name unavailable for {id_}: HTTP {exc.code}", flush=True)
            continue
        except (urllib.error.URLError, ValueError) as exc:
            print(f"Game-page name unavailable for {id_}: {exc}", flush=True)
            continue
        title = game_page_name(markup)
        if title:
            games[id_]["name"] = title
            named += 1
        else:
            print(f"No usable game heading for {id_}", flush=True)
        time.sleep(0.5)
    print(f"Named {named} additional games from detail pages; "
          f"{sum(not row['name'] for row in games.values())} still unnamed",
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=Path("data/notultranx-seed.json"))
    parser.add_argument("--output", type=Path, default=Path("data/notultranx-catalog.json"))
    parser.add_argument("--scan-site", action="store_true",
                        help="Scan all public listing pages; fail on incomplete scan")
    parser.add_argument("--pages-dir", type=Path,
                        help="Use cached notultranx-page-N.html files from a laptop")
    parser.add_argument("--max-pages", type=int, default=96)
    parser.add_argument("--skip-metadata", action="store_true",
                        help="Skip remote TitleDB enrichment (offline import)")
    parser.add_argument("--titledb", default=TITLEDB)
    args = parser.parse_args()
    games = load_catalog(args.seed)
    if len(games) < 20:
        raise SystemExit("Seed catalog missing or too small; refusing to replace output.")
    for id_, row in load_catalog(args.output).items():
        if id_ not in games:
            games[id_] = row
        elif not games[id_]["name"] and row["name"]:
            games[id_]["name"] = row["name"]
    if args.scan_site or args.pages_dir is not None:
        merge_site_ids(games, max(1, min(args.max_pages, 96)), args.pages_dir)
    if not args.skip_metadata:
        add_metadata(games, args.titledb)
        enrich_missing_site_names(games)
    if len(games) < 20:
        raise SystemExit("Refusing to publish empty catalog")
    document = {
        "schemaVersion": 1,
        "source": SITE,
        "nameSource": args.titledb,
        "games": [games[id_] for id_ in sorted(games)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_name(args.output.name + ".part")
    temp.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    temp.replace(args.output)
    total_named = sum(bool(row["name"]) for row in games.values())
    print(f"Saved {len(games)} IDs ({total_named} named) to {args.output}", flush=True)


if __name__ == "__main__":
    main()
