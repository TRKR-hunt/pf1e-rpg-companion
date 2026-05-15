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
        "recursive": False,
        "excluded": ("/3rd-party", "/npc-classes", "/monster-classes",
                     "/class-archetypes", "/prestige-classes",
                     "/character-advancement", "/archetypes"),
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
        "recursive": True,
        "excluded": ("/3rd-party",),
    },
    "archetype": {
        "compendium_category": "archetype",
        # Archetypes don't share one path prefix — they live under each
        # class as /classes/<cat>/<class>/archetypes/<publisher>/<arch>.
        # discover_archetypes() handles the bespoke walk; these class
        # index roots are the starting points (same set as "class").
        "class_index_roots": [
            f"{BASE}/classes/core-classes/",
            f"{BASE}/classes/base-classes/",
            f"{BASE}/classes/hybrid-classes/",
            f"{BASE}/classes/unchained-classes/",
            f"{BASE}/classes/alternate-classes/",
        ],
        "path_prefix": "/classes/",
        "excluded": ("/3rd-party",),
    },
    "deity": {
        "compendium_category": "deity",
        "index_roots": [f"{BASE}/gods-and-magic/"],
        "path_prefix": "/gods-and-magic/",
        "detail_depth": 3,
        "recursive": True,
        "excluded": ("/3rd-party",),
    },
    "race_lore": {
        "compendium_category": "race_lore",
        "index_roots": [
            f"{BASE}/races/core-races/",
            f"{BASE}/races/other-races/featured-races/",
            f"{BASE}/races/other-races/uncommon-races/",
            f"{BASE}/races/other-races/more-races/",
        ],
        "path_prefix": "/races/",
        "detail_depth": 3,
        "recursive": True,
        "excluded": ("/3rd-party",),
        # Tails containing "races" (core-races, featured-races,
        # standard-races-1-10-rp, ...) are sub-indexes to recurse, not
        # detail pages. Detail race slugs (arg-catfolk, gnoll-6-rp)
        # don't contain "races".
        "extra_index_substrings": ("races",),
    },
}

# The 7 hand-authored mechanical PF1e races, keyed by lowercased name,
# so a scraped core-race lore entry can cross-link to the real
# mechanical race resource.
MECHANICAL_RACE_IDS = {
    "dwarf": "race_dwarf__crb_",
    "elf": "race_elf__crb_",
    "gnome": "race_gnome__crb_",
    "half-elf": "race_half-elf__crb_",
    "half-orc": "race_half-orc__crb_",
    "halfling": "race_halfling__crb_",
    "human": "race_human__crb_",
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


def _looks_like_index_tail(tail: str, extra_substrings: tuple = ()) -> bool:
    if bool(_INDEX_TAIL_RE.match(tail)) or tail in _INDEX_TAIL_NAMES \
            or tail.endswith("-classes") or tail.endswith("-archetypes"):
        return True
    return any(sub in tail for sub in extra_substrings)


def discover(cfg: dict) -> dict[str, str]:
    """Return {detail_url: name} for every detail page under the
    configured index roots. Recurses through sub-index pages
    (alpha-bucket / category sub-pages) up to the detail depth."""
    out: dict[str, str] = {}
    prefix = cfg["path_prefix"]
    depth = cfg["detail_depth"]
    excluded = cfg["excluded"]
    recursive = cfg.get("recursive", False)
    visited: set[str] = set()
    queue: list[str] = list(cfg["index_roots"])
    # For non-recursive categories, a detail page must be a DIRECT child
    # of one of the configured index roots (so index-page sidebar links
    # to feature sub-pages — Bloodlines, Hexes, Arcane Schools — don't
    # masquerade as class detail pages).
    root_paths = {urlparse(r).path.rstrip("/") for r in cfg["index_roots"]}

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
            extra = cfg.get("extra_index_substrings", ())
            is_index = _looks_like_index_tail(tail, extra)
            if is_index:
                # A sub-index. Recurse into it (recursive categories only),
                # regardless of depth — nested buckets can sit deeper than
                # detail_depth (e.g. races more-races/standard-races-1-10-rp).
                if recursive and href not in visited and path != root.rstrip("/"):
                    queue.append(href)
            elif n >= depth:
                # A detail page.
                if not recursive:
                    # Must be a direct child of a configured index root.
                    parent = path.rsplit("/", 1)[0]
                    if parent not in root_paths:
                        continue
                if name and len(name) <= 120:
                    out.setdefault(href, name)
    return out


def _discover_class_urls(class_index_roots: list[str]) -> dict[str, str]:
    """Return {class_detail_url: class_name} — the ~40 playable classes,
    excluding 3rd-party / npc / monster / archetype / prestige paths."""
    out: dict[str, str] = {}
    excl = ("/3rd-party", "/npc-classes", "/monster-classes",
            "/class-archetypes", "/prestige-classes", "/character-advancement")
    for root in class_index_roots:
        try:
            html = scrape_lib.fetch(root)
        except Exception as e:
            print(f"  ! class index fetch failed {root}: {e}")
            continue
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("div", id="article-content") or soup
        for a in content.find_all("a", href=True):
            href = _canonicalize_href(urljoin(root, a["href"]))
            path = urlparse(href).path.rstrip("/")
            if not path.startswith("/classes/"):
                continue
            if any(x in path for x in excl):
                continue
            segs = [s for s in path.split("/") if s]
            if len(segs) != 3:
                continue
            tail = segs[-1]
            if tail.endswith("-classes") or tail == "classes":
                continue
            name = a.get_text(" ", strip=True)
            if name and len(name) <= 120:
                out.setdefault(href, name)
    return out


def discover_archetypes(cfg: dict) -> dict[str, dict]:
    """Walk every playable class → its /archetypes/ index → the Paizo
    publisher bucket → individual archetype detail pages.

    Returns {detail_url: {"name", "parent_class_name",
    "related_mechanical_resource_id"}}."""
    out: dict[str, dict] = {}
    class_urls = _discover_class_urls(cfg["class_index_roots"])
    print(f"  walking {len(class_urls)} class pages for archetypes...")
    for class_url, class_name in sorted(class_urls.items()):
        class_path = urlparse(class_url).path.rstrip("/")
        arch_index = f"{BASE}{class_path}/archetypes/"
        try:
            html = scrape_lib.fetch(arch_index)
        except Exception:
            continue  # class has no archetypes index
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("div", id="article-content") or soup
        # Find Paizo publisher bucket link(s) on the archetypes index.
        paizo_buckets: set[str] = set()
        base_depth = len([s for s in class_path.split("/") if s]) + 1  # + 'archetypes'
        for a in content.find_all("a", href=True):
            href = _canonicalize_href(urljoin(arch_index, a["href"]))
            p = urlparse(href).path.rstrip("/")
            if f"{class_path}/archetypes" not in p:
                continue
            tail = p.rsplit("/", 1)[-1]
            if "paizo" in tail:
                paizo_buckets.add(href)
        rel_id = MECHANICAL_CLASS_IDS.get(class_name.strip().lower(), "")
        for bucket in paizo_buckets:
            try:
                bhtml = scrape_lib.fetch(bucket)
            except Exception:
                continue
            bsoup = BeautifulSoup(bhtml, "html.parser")
            bcontent = bsoup.find("div", id="article-content") or bsoup
            bucket_path = urlparse(bucket).path.rstrip("/")
            for a in bcontent.find_all("a", href=True):
                href = _canonicalize_href(urljoin(bucket, a["href"]))
                p = urlparse(href).path.rstrip("/")
                if not p.startswith(bucket_path + "/"):
                    continue
                if "/3rd-party" in p:
                    continue
                segs = [s for s in p.split("/") if s]
                # Detail page sits exactly one level below the bucket.
                if len(segs) != len([s for s in bucket_path.split("/") if s]) + 1:
                    continue
                name = a.get_text(" ", strip=True)
                if not name or len(name) > 120:
                    continue
                low = name.lower()
                if low.startswith("go to ") or low in ("next", "previous", "back"):
                    continue
                out.setdefault(href, {
                    "name": name,
                    "parent_class_name": class_name,
                    "related_mechanical_resource_id": rel_id,
                })
    return out


_PREREQ_RE = re.compile(
    r"(?:^|\n)\s*(Requirements?|Prerequisites?|Role|Alignment|Hit Die)\s*:?\s*",
    re.IGNORECASE,
)


def parse_detail(name: str, url: str, cfg: dict,
                 related_override: str = "") -> dict | None:
    html = scrape_lib.fetch(url)
    source_id, _ = scrape_lib.extract_section_15_source(html)

    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()
    body = content.get_text("\n", strip=True)
    # Strip the breadcrumb trail. d20pfsrd renders it as a chain of
    # "Home > Section > Subsection > Leaf" (case/word may differ from the
    # link text, e.g. "Dwarves" vs name "dwarves"). Drop everything up to
    # and including the last ">" of the leading breadcrumb run.
    body = re.sub(
        r"^\s*Home\s*(?:>\s*[^\n>]+\s*){1,6}",
        "", body, count=1, flags=re.IGNORECASE,
    )
    body = re.sub(rf"^\s*{re.escape(name)}\s*\n+", "", body, count=1,
                  flags=re.IGNORECASE)
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

    related = related_override or ""
    if not related and compendium_cat == "class":
        related = MECHANICAL_CLASS_IDS.get(name.strip().lower(), "")
    if not related and compendium_cat == "race_lore":
        rn = name.strip().lower()
        # d20pfsrd's core-race index links use plurals ("Elves",
        # "Dwarves"). Normalize to the mechanical-race singular key.
        _plural_to_singular = {
            "elves": "elf", "dwarves": "dwarf", "gnomes": "gnome",
            "halflings": "halfling", "humans": "human",
            "half-elves": "half-elf", "half-orcs": "half-orc",
        }
        rn = _plural_to_singular.get(rn, rn)
        related = MECHANICAL_RACE_IDS.get(rn, "")

    # Namespace the id by category: every compendium_entry shares the
    # compendium_entry_<id>.rpg.json filename space, so an archetype
    # named "duelist" must not clobber the "duelist" prestige class.
    inst_id = f"{compendium_cat}_{_url_slug(url)}__crb_"
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
                slug_buckets: dict, related_override: str = "") -> str | None:
    entry = parse_detail(name, url, cfg, related_override=related_override)
    if not entry:
        return None
    base_slug = _url_slug(url)
    if len(slug_buckets.get(base_slug, [])) > 1:
        cat = entry["stats"]["category"]["value"]
        entry["stats"]["id"] = f"{cat}_{_url_path_slug(url, cfg['path_prefix'])}__crb_"
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

    # Archetypes use a bespoke per-class walk; everything else uses the
    # generic recursive discover(). Normalize both to {url: meta-dict}.
    if args.category == "archetype":
        print("Discovering archetypes (per-class Paizo buckets)...")
        raw = discover_archetypes(cfg)
        found = {u: m for u, m in raw.items()}
    else:
        print(f"Discovering {args.category} from {len(cfg['index_roots'])} index roots")
        found = {u: {"name": n, "related_mechanical_resource_id": ""}
                 for u, n in discover(cfg).items()}

    print(f"Total unique {args.category} detail URLs: {len(found)}")
    for url, meta in sorted(found.items())[:20]:
        print(f"  {meta['name'][:40]!r} {urlparse(url).path}")
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

    triples = [(meta["name"], url, None) for url, meta in items]
    unique_names = scrape_lib.disambiguate_names(triples)

    def task(item_and_name):
        (url, meta), display_name = item_and_name
        return write_entry(meta["name"], url, cfg, display_name, slug_buckets,
                           related_override=meta.get("related_mechanical_resource_id", ""))

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
