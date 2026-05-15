#!/usr/bin/env python3
"""Generic d20pfsrd → compendium_entry scraper.

For lore-rich, mechanics-thin content where d20pfsrd's page is
descriptive prose rather than a parseable rules block. One scraper,
many categories — Section 4 (classes), Section 5 (prestige classes),
Section 6 (archetypes), Section 10 (deities) all run through here.

Each emitted instance is a `compendium_entry` resource with the
section's `category` enum id. When a scraped entry has a hand-authored
mechanical counterpart (e.g. the 11 curated classes), its
`related_mechanical_resource_id` is set so the UI can cross-link.

Usage:
    python scrape_compendium.py --category class --discover-only
    python scrape_compendium.py --category class --limit 10
    python scrape_compendium.py --category class
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

import scrape_lib

BASE = "https://www.d20pfsrd.com"
OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

# Per-section configuration.
#   index_roots: d20pfsrd category index pages to walk
#   detail_depth: path-segment count that identifies a detail page
#   excluded: substrings that disqualify a path (3rd-party / NPC / monster)
CATEGORY_CONFIG: dict[str, dict] = {
    "class": {
        "compendium_category": "class",
        "index_roots": [
            f"{BASE}/classes/core-classes/",
            f"{BASE}/classes/base-classes/",
            f"{BASE}/classes/hybrid-classes/",
            f"{BASE}/classes/unchained-classes/",
            f"{BASE}/classes/alternate-classes/",
        ],
        "path_prefix": "/classes/",
        "detail_depth": 3,
        "excluded": ("/3rd-party", "/npc-classes", "/monster-classes",
                     "/class-archetypes", "/prestige-classes",
                     "/character-advancement"),
    },
    "prestige_class": {
        "compendium_category": "prestige_class",
        "index_roots": [
            f"{BASE}/classes/prestige-classes/core-rulebook/",
            f"{BASE}/classes/prestige-classes/apg/",
            f"{BASE}/classes/prestige-classes/other-paizo/",
        ],
        "path_prefix": "/classes/prestige-classes/",
        "detail_depth": 4,
        "excluded": ("/3rd-party",),
    },
    "archetype": {
        "compendium_category": "archetype",
        "index_roots": [f"{BASE}/classes/class-archetypes/"],
        "path_prefix": "/classes/class-archetypes/",
        "detail_depth": 4,
        "excluded": ("/3rd-party",),
    },
    "deity": {
        "compendium_category": "deity",
        "index_roots": [f"{BASE}/gods-and-magic/"],
        "path_prefix": "/gods-and-magic/",
        "detail_depth": 3,
        "excluded": ("/3rd-party",),
    },
}

# Hand-authored mechanical class ids, keyed by lowercased class name, so
# scraped class entries can cross-link to the real mechanical resource.
MECHANICAL_CLASS_IDS = {
    "barbarian": "class_barbarian__crb_",
    "bard": "class_bard__crb_",
    "cleric": "class_cleric__crb_",
    "druid": "class_druid__crb_",
    "fighter": "class_fighter__crb_",
    "monk": "class_monk__crb_",
    "paladin": "class_paladin__crb_",
    "ranger": "class_ranger__crb_",
    "rogue": "class_rogue__crb_",
    "sorcerer": "class_sorcerer__crb_",
    "wizard": "class_wizard__crb_",
}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _canonicalize_href(href: str) -> str:
    parsed = urlparse(href)
    segs = [s.strip("-").lower() for s in parsed.path.split("/")]
    new_path = "/".join(segs)
    if not new_path.endswith("/"):
        new_path += "/"
    return urlunparse(parsed._replace(path=new_path, fragment="", query=""))


def _url_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return slugify(path.rsplit("/", 1)[-1])


def _url_path_slug(url: str, prefix: str) -> str:
    path = urlparse(url).path.rstrip("/")
    if path.startswith(prefix):
        path = path[len(prefix):]
    return slugify(path)


def _collapse_inline_newlines(text: str) -> str:
    PARA = "␟"
    text = re.sub(r"\n{2,}", PARA, text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = text.replace(PARA, "\n\n")
    text = re.sub(r"  +", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    return text.strip()


# Path tails that denote an INDEX page to recurse into, not a detail
# page: alpha buckets (a, a-b, c-d), and known sub-index segment names.
_INDEX_TAIL_RE = re.compile(r"^[a-z](?:-[a-z])?$")
_INDEX_TAIL_NAMES = {
    "core-rulebook", "apg", "other-paizo", "acg", "arg", "um", "uc",
}


def _looks_like_index_tail(tail: str) -> bool:
    return bool(_INDEX_TAIL_RE.match(tail)) or tail in _INDEX_TAIL_NAMES \
        or tail.endswith("-classes") or tail.endswith("-archetypes")


def discover(cfg: dict) -> dict[str, str]:
    """Return {detail_url: name} for every detail page under the
    configured index roots. Recurses through sub-index pages
    (alpha-bucket / category sub-pages) up to the detail depth."""
    out: dict[str, str] = {}
    prefix = cfg["path_prefix"]
    depth = cfg["detail_depth"]
    excluded = cfg["excluded"]
    visited: set[str] = set()
    queue: list[str] = list(cfg["index_roots"])

    while queue:
        root = queue.pop()
        if root in visited:
            continue
        visited.add(root)
        try:
            html = scrape_lib.fetch(root)
        except Exception as e:
            print(f"  ! index fetch failed {root}: {e}")
            continue
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("div", id="article-content") or soup
        for a in content.find_all("a", href=True):
            href = _canonicalize_href(urljoin(root, a["href"]))
            path = urlparse(href).path.rstrip("/")
            if not path.startswith(prefix):
                continue
            if any(x in path for x in excluded):
                continue
            segs = [s for s in path.split("/") if s]
            n = len(segs)
            if n == 0:
                continue
            tail = segs[-1]
            name = a.get_text(" ", strip=True)
            low = name.lower()
            if low.startswith("go to ") or low in ("next", "previous", "back"):
                continue
            if n >= depth and not _looks_like_index_tail(tail):
                # A detail page.
                if name and len(name) <= 120:
                    out.setdefault(href, name)
            elif n < depth and _looks_like_index_tail(tail) and href not in visited:
                # A sub-index to recurse into.
                queue.append(href)
    return out


_PREREQ_RE = re.compile(
    r"(?:^|\n)\s*(Requirements?|Prerequisites?|Role|Alignment|Hit Die)\s*:?\s*",
    re.IGNORECASE,
)


def parse_detail(name: str, url: str, cfg: dict) -> dict | None:
    html = scrape_lib.fetch(url)
    source_id, _ = scrape_lib.extract_section_15_source(html)

    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()
    body = content.get_text("\n", strip=True)
    # Strip the breadcrumb trail. d20pfsrd renders it as a chain of
    # "> Section > Subsection > Name" with or without a leading "Home".
    body = re.sub(r"^\s*(?:Home\s*)?(?:>\s*[^\n>]+\s*)+>\s*"
                  + re.escape(name) + r"\s*", "", body, count=1)
    body = re.sub(rf"^\s*{re.escape(name)}\s*\n+", "", body, count=1)
    # Strip the in-page "Contents ..." table-of-contents line(s) that
    # d20pfsrd injects right after the breadcrumb.
    body = re.sub(r"^\s*Contents\b[^\n]*\n", "", body, count=1)
    # Drop the Section 15 OGL trailer from the description body.
    cut = re.search(r"\n?Section 15\s*:", body, re.IGNORECASE)
    if cut:
        body = body[: cut.start()]
    description = _collapse_inline_newlines(body)[:8000]

    compendium_cat = cfg["compendium_category"]

    # Prerequisites text only makes sense for prestige classes /
    # archetypes (which have explicit "Requirements:" blocks). For plain
    # classes the regex just grabs prose, so skip it there.
    prereq = ""
    if compendium_cat in ("prestige_class", "archetype"):
        m = _PREREQ_RE.search(body)
        if m:
            seg = body[m.end(): m.end() + 400]
            prereq = _collapse_inline_newlines(seg.split("\n")[0])[:600]

    related = ""
    if compendium_cat == "class":
        related = MECHANICAL_CLASS_IDS.get(name.strip().lower(), "")

    inst_id = f"{_url_slug(url)}__crb_"
    return {
        "resource_id": "compendium_entry",
        "stats": {
            "id": inst_id,
            "name": {"value": name},
            "source": {"value": source_id},
            "category": {"value": compendium_cat},
            "prerequisites_text": {"value": prereq},
            "description": {"value": description},
            "related_mechanical_resource_id": {"value": related},
        },
    }


def write_entry(name: str, url: str, cfg: dict, display_name: str,
                slug_buckets: dict) -> str | None:
    entry = parse_detail(name, url, cfg)
    if not entry:
        return None
    base_slug = _url_slug(url)
    if len(slug_buckets.get(base_slug, [])) > 1:
        entry["stats"]["id"] = f"{_url_path_slug(url, cfg['path_prefix'])}__crb_"
    entry["stats"]["name"]["value"] = display_name
    out_path = OUT_DIR / f"compendium_entry_{entry['stats']['id']}.rpg.json"
    out_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return out_path.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", required=True, choices=list(CATEGORY_CONFIG))
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = CATEGORY_CONFIG[args.category]

    print(f"Discovering {args.category} from {len(cfg['index_roots'])} index roots")
    found = discover(cfg)
    print(f"Total unique {args.category} detail URLs: {len(found)}")
    for url, name in sorted(found.items())[:20]:
        print(f"  {name[:40]!r} {urlparse(url).path}")
    if len(found) > 20:
        print(f"  ... and {len(found) - 20} more")

    if args.discover_only:
        return

    items = sorted(found.items())
    if args.limit:
        items = items[: args.limit]
        print(f"\n--limit {args.limit}: scraping first {len(items)} only.")

    slug_buckets: dict[str, list] = {}
    for url, _ in items:
        slug_buckets.setdefault(_url_slug(url), []).append(url)

    triples = [(name, url, None) for url, name in items]
    unique_names = scrape_lib.disambiguate_names(triples)

    def task(item_and_name):
        (url, name), display_name = item_and_name
        return write_entry(name, url, cfg, display_name, slug_buckets)

    print(f"\nScraping {len(items)} {args.category} with {scrape_lib.WORKERS} workers...")
    scrape_lib.reset_hard_stop()
    scrape_lib.reset_source_trackers()
    paired = list(zip(items, unique_names))
    results = scrape_lib.parallel_map(paired, task, label=args.category)
    written = sum(1 for r in results if r)
    failed = sum(1 for r in results if r is None)
    print(f"\nDone: wrote {written} {args.category} entries, {failed} failures/skips.")
    slug_count = len({scrape_lib.compiler_slug(dn) for dn in unique_names})
    print(f"Unique compiler-slug names: {slug_count} (expect == {written})")
    print(f"Source attribution: {len(scrape_lib.seen_sources)} distinct ids")
    if scrape_lib.unknown_sources:
        nosec15 = scrape_lib.unknown_sources.get("__no_section_15__", 0)
        unmapped = sum(1 for k in scrape_lib.unknown_sources if k != "__no_section_15__")
        print(f"  {nosec15} pages had no Section 15 footer (-> 'unknown')")
        print(f"  {unmapped} distinct book strings auto-derived")


if __name__ == "__main__":
    main()
