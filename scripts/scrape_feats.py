#!/usr/bin/env python3
"""d20pfsrd feat scraper for the PF1e RPG Companion App system build.

Discovers feat categories from the /feats/ root, walks each Players-side
category's index, and writes one .rpg.json per unique feat detail page
into ../resource_instances/.

Uses scrape_lib for concurrency, caching, UA, and hard-stop guardrails.

Usage:
    python scrape_feats.py --discover-only        # list counts, no scrape
    python scrape_feats.py --limit 10             # smoke test
    python scrape_feats.py                        # full scrape
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import scrape_lib

BASE = "https://www.d20pfsrd.com"
ROOT_URL = f"{BASE}/feats/"
OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

# Players-side category URL prefix → our feat_types enum id.
# Path-prefixed so subcategories under e.g. /feats/combat-feats/critical-feats/
# still match. Order matters — more specific prefixes first.
CATEGORY_RULES: list[tuple[str, str]] = [
    ("/feats/combat-feats/critical-feats", "combat"),
    ("/feats/combat-feats", "combat"),
    ("/feats/general-feats", "general"),
    ("/feats/item-creation-feats", "item_creation"),
    ("/feats/metamagic-feats", "metamagic"),
    ("/feats/teamwork-feats", "teamwork"),
    ("/feats/style-feats", "style"),
    ("/feats/racial-feats", "racial"),
    ("/feats/grit-feats", "combat"),
    ("/feats/panache-feats", "combat"),
    ("/feats/weapon-mastery-feats", "combat"),
    ("/feats/item-mastery-feats", "general"),
    ("/feats/performance-feats", "general"),
    ("/feats/channeling-feats", "general"),
    ("/feats/conduit-feats", "general"),
    ("/feats/damnation-feats", "general"),
    ("/feats/stare-feats", "general"),
    ("/feats/caravan-feats", "general"),
    ("/feats/local-feats", "general"),
    ("/feats/story-feats", "general"),
    ("/feats/achievement-feats", "general"),
    ("/feats/betrayal-feats", "general"),
    ("/feats/hero-point-feats", "general"),
]

# Categories explicitly NOT in Players-side scope.
EXCLUDED_PREFIXES = (
    "/feats/3rd-party-feats",
    "/feats/monster-feats",
    "/feats/animal-companion-feats",   # Section 12 will handle these
)

# Path tails that are not feat detail pages (nav / listing / tooling).
NON_DETAIL_TAILS = {
    "feats", "tools", "publishers",
}

# Suffixes used by d20pfsrd for listing-type pages.
def _is_listing_path(path: str) -> bool:
    p = path.rstrip("/")
    if p.endswith("-feats"):
        return True
    if p.endswith("/all-feats"):
        return True
    return False


def _is_excluded(path: str) -> bool:
    """Match the EXCLUDED_PREFIXES anywhere in the path, not just at start.
    d20pfsrd nests 3rd-party feats under category roots (e.g.
    /feats/style-feats/3rd-party-feats/...), so a startswith check would
    miss them."""
    p = path
    if any(p.startswith(pref) for pref in EXCLUDED_PREFIXES):
        return True
    # Substring matches for nested 3rd-party / monster paths.
    for needle in ("/3rd-party-feats/", "/monster-feats/", "/animal-companion-feats/"):
        if needle in p:
            return True
    return False


def _categorize(path: str) -> str | None:
    """Return our feat_types id for this URL path, or None if out-of-scope."""
    if _is_excluded(path):
        return None
    for prefix, cat in CATEGORY_RULES:
        if path.startswith(prefix):
            return cat
    return None


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _url_slug(url: str) -> str:
    """Last non-empty path segment, slugified. Suitable as a short id when
    no other URL shares the same final segment."""
    path = urlparse(url).path.rstrip("/")
    last = path.rsplit("/", 1)[-1]
    return slugify(last)


def _url_path_slug(url: str, root: str = "/feats/") -> str:
    """Slug of the URL path after the given root. Unique per d20pfsrd URL,
    even when same-named pages exist across categories (e.g.
    /feats/combat-feats/dodge/ vs /feats/general-feats/dodge/)."""
    path = urlparse(url).path.rstrip("/")
    if path.startswith(root):
        path = path[len(root):]
    return slugify(path)


def _collapse_inline_newlines(text: str) -> str:
    """Same fix as the trait scraper: BeautifulSoup's get_text("\\n") splits
    inline-link text nodes onto their own lines. Collapse single newlines
    (mid-sentence) to spaces, preserve paragraph breaks."""
    PARA = "␟"  # private placeholder
    text = re.sub(r"\n{2,}", PARA, text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = text.replace(PARA, "\n\n")
    text = re.sub(r"  +", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    return text.strip()


# ---------- discovery ----------

def discover_category_indexes() -> dict[str, str]:
    """From /feats/ root, return {category_index_url: feat_type_id} for
    every Players-side category we know how to map."""
    html = scrape_lib.fetch(ROOT_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    indexes: dict[str, str] = {}
    for a in content.find_all("a", href=True):
        href = urljoin(ROOT_URL, a["href"])
        path = urlparse(href).path.rstrip("/")
        if not path.startswith("/feats/"):
            continue
        if not _is_listing_path(path):
            continue
        cat = _categorize(path)
        if cat is None:
            continue
        # Normalize to canonical (trailing slash, no fragment).
        canon = f"{BASE}{path}/"
        indexes[canon] = cat
    return indexes


def find_feat_links(index_url: str) -> list[tuple[str, str]]:
    """Pull (name, detail_url) pairs from a feat category/listing page.
    Filters listing/nav links."""
    html = scrape_lib.fetch(index_url)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    # Strip the obvious noise wrappers before walking.
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    self_path = urlparse(index_url).path.rstrip("/")
    for a in content.find_all("a", href=True):
        href = urljoin(index_url, a["href"])
        if "#" in href:
            continue
        path = urlparse(href).path.rstrip("/")
        # Canonicalize the href so trivial typos on d20pfsrd collapse to
        # the same URL: trailing-slash form, lowercase path, segments
        # stripped of leading/trailing dashes.
        from urllib.parse import urlunparse
        parsed = urlparse(href)
        segs = [s.strip("-").lower() for s in parsed.path.split("/")]
        new_path = "/".join(segs)
        if not new_path.endswith("/"):
            new_path += "/"
        href = urlunparse(parsed._replace(path=new_path))
        path = new_path.rstrip("/")
        if not path.startswith("/feats/"):
            continue
        if path == self_path:
            continue
        if _is_listing_path(path):
            continue
        # Skip excluded categories even if linked from a kept category.
        if _is_excluded(path):
            continue
        tail = path.rsplit("/", 1)[-1]
        if not tail or tail in NON_DETAIL_TAILS:
            continue
        # Reject URLs deeper than /feats/<category>-feats/<subcat-feats>/<slug>.
        # d20pfsrd's relative-link parsing sometimes produces
        # /feats/<cat>/<feat>/<another-feat>/, which 503s when fetched
        # (page doesn't exist). Valid 4-deep URLs require the 3rd segment
        # to be a -feats category (combat-feats/critical-feats/slug).
        segs = [s for s in path.split("/") if s]
        if len(segs) >= 4 and not segs[-2].endswith("-feats"):
            continue
        if len(segs) > 4:
            continue
        name = a.get_text(" ", strip=True)
        if not name or len(name) > 120:
            continue
        # Visible nav strings we've seen in early smoke runs.
        low = name.lower()
        if low.startswith("go to the ") or low in {"feats", "next", "previous"}:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append((name, href))
    return out


def discover_all_feats() -> dict[str, dict]:
    """Walk every Players-side category index. Return
    {detail_url: {"name", "category", "categories"}}.
    Same URL can appear in multiple categories — we keep the FIRST per
    CATEGORY_RULES priority order.
    """
    indexes = discover_category_indexes()
    # Map category-id -> ordered priority (lower is more authoritative).
    priority = {cat: i for i, (_, cat) in enumerate(CATEGORY_RULES)}
    all_feats: dict[str, dict] = {}
    for idx_url, cat in indexes.items():
        for name, detail_url in find_feat_links(idx_url):
            existing = all_feats.get(detail_url)
            if existing is None or priority.get(cat, 999) < priority.get(existing["category"], 999):
                if existing is None:
                    all_feats[detail_url] = {"name": name, "category": cat, "categories": {cat}}
                else:
                    existing["category"] = cat
                    existing["categories"].add(cat)
            else:
                existing["categories"].add(cat)
    return all_feats


# ---------- parsing ----------

_FIELD_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(Prerequisites?|Benefits?|Normal|Special|Trigger|Frequency|Requirements?)"
    r"(?:\(s\))?\s*:?\s*",
    re.IGNORECASE,
)


def _strip_trailers(body: str) -> str:
    cut = re.search(r"\n?Section 15\s*:", body, re.IGNORECASE)
    if cut:
        body = body[: cut.start()]
    return body.strip()


def _split_into_fields(body: str) -> dict[str, str]:
    body = _strip_trailers(body)
    matches = list(_FIELD_LABEL_RE.finditer(body))
    if not matches:
        return {"description": body}
    fields: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(1).lower().rstrip("s")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        if label in fields:
            fields[label] = fields[label] + "\n\n" + chunk
        else:
            fields[label] = chunk
    return fields


def parse_feat_page(name: str, url: str, category: str) -> dict | None:
    html = scrape_lib.fetch(url)
    # Extract source from Section 15 OGL footer before body parsing.
    source_id, _book_raw = scrape_lib.extract_section_15_source(html)

    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()
    body = content.get_text("\n", strip=True)
    body = re.sub(r"^\s*Home\b[\s>\n]+[^\n]+\n", "", body)
    body = re.sub(rf"^\s*{re.escape(name)}\s*\n+", "", body, count=1)

    fields = _split_into_fields(body)

    prereq = _collapse_inline_newlines(fields.get("prerequisite", ""))
    benefit = _collapse_inline_newlines(fields.get("benefit", ""))
    normal = _collapse_inline_newlines(fields.get("normal", ""))
    special = _collapse_inline_newlines(fields.get("special", ""))

    description_parts: list[str] = []
    if benefit:
        description_parts.append(f"**Benefit:** {benefit}")
    if normal:
        description_parts.append(f"**Normal:** {normal}")
    if special:
        description_parts.append(f"**Special:** {special}")
    description = "\n\n".join(description_parts)
    if not description:
        description = _collapse_inline_newlines(body.strip())
    description = description[:4000]

    feat_id = f"feat_{_url_slug(url)}__crb_"
    return {
        "resource_id": "feat",
        "stats": {
            "id": feat_id,
            "name": {"value": name},
            "source": {"value": source_id},
            "type": {"value": category},
            "traits": {"value": category},
            "prerequisites": {"value": prereq[:400]},
            "description": {"value": description},
            "action_cost": {"value": "passive"},
            "is_toggleable": {"value": False},
            "effects": {"value": []},
        },
    }


def _is_curated(out_path: Path) -> bool:
    """A file is curated if it already exists and contains non-empty effects.
    Curated feats are hand-authored with rich mechanics; scraped feats
    have effects=[] (just description text). Never overwrite a curated
    file with a scraped version."""
    if not out_path.exists():
        return False
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        effects = data.get("stats", {}).get("effects", {}).get("value", [])
        return bool(effects)
    except Exception:
        return False


def write_feat(name: str, url: str, category: str, display_name: str,
                slug_buckets: dict) -> str | None:
    """parse + write; returns the filename written, or None on failure.

    `display_name` is the name-disambiguator output for this feat (may
    equal `name` for the bare-name winner of a colliding group, or be
    parenthetically suffixed for losers)."""
    feat = parse_feat_page(name, url, category)
    if not feat:
        return None
    base_slug = _url_slug(url)
    # ID-level disambiguation: when more than one URL maps to the same
    # final-segment slug, use the full URL path slug (which is unique
    # per URL — guaranteed by the site structure). This catches both
    # cross-category collisions (combat-feats/dodge vs general-feats/
    # dodge) and within-category sub-category collisions (combat-feats/
    # dodge vs combat-feats/critical-feats/dodge).
    if len(slug_buckets.get(base_slug, [])) > 1:
        feat["stats"]["id"] = f"feat_{_url_path_slug(url)}__crb_"
    # Name-level disambiguation so the compiler-emitted per-resource
    # filename doesn't collapse across same-named feats.
    feat["stats"]["name"]["value"] = display_name
    out_path = OUT_DIR / f"{feat['stats']['id']}.rpg.json"
    # Don't clobber hand-curated feats that have real `effects` defined.
    if _is_curated(out_path):
        return None
    out_path.write_text(json.dumps(feat, indent=2), encoding="utf-8")
    return out_path.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover-only", action="store_true",
                    help="Discover and count, do not scrape detail pages.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N feats (smoke test).")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Discovering feat categories from {ROOT_URL}")
    indexes = discover_category_indexes()
    print(f"Found {len(indexes)} Players-side category index pages.")

    all_feats = discover_all_feats()
    print(f"\nTotal unique feat URLs discovered: {len(all_feats)}")
    # Per-category counts (using primary category).
    by_cat: dict[str, int] = {}
    for v in all_feats.values():
        by_cat[v["category"]] = by_cat.get(v["category"], 0) + 1
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}")

    if args.discover_only:
        return

    items = sorted(all_feats.items())  # deterministic
    if args.limit:
        items = items[: args.limit]
        print(f"\n--limit {args.limit}: scraping first {len(items)} only.")

    # ID-level disambiguation buckets (URL-slug collisions).
    slug_buckets: dict[str, list] = {}
    for url, meta in items:
        slug_buckets.setdefault(_url_slug(url), []).append(url)

    # NAME-level disambiguation: the bundled compiler derives the per-
    # resource output filename from the `name` stat. Many feats share
    # names across categories or share with same-cat variants (Power
    # Attack, Improved Initiative, …). Pre-compute unique display names
    # so the compiler emits one .rpg per id.
    triples = [(meta["name"], url, meta["category"]) for url, meta in items]
    unique_names = scrape_lib.disambiguate_names(triples)

    def task(item_and_name):
        (url, meta), display_name = item_and_name
        return write_feat(meta["name"], url, meta["category"], display_name, slug_buckets)

    print(f"\nScraping {len(items)} feats with {scrape_lib.WORKERS} workers...")
    scrape_lib.reset_hard_stop()
    scrape_lib.reset_source_trackers()
    paired = list(zip(items, unique_names))
    results = scrape_lib.parallel_map(paired, task, label="feat")
    written = sum(1 for r in results if r)
    failed = sum(1 for r in results if r is None)
    print(f"\nDone: wrote {written} feats, {failed} failures/skips.")
    slug_count = len({scrape_lib.compiler_slug(dn) for dn in unique_names})
    print(f"Unique compiler-slug names: {slug_count} (expect == {written})")
    print(f"\nSource attribution: {len(scrape_lib.seen_sources)} distinct ids")
    if scrape_lib.unknown_sources:
        unmapped = sum(1 for k in scrape_lib.unknown_sources if k != "__no_section_15__")
        nosec15 = scrape_lib.unknown_sources.get("__no_section_15__", 0)
        print(f"  {nosec15} pages had no Section 15 footer (-> 'unknown')")
        print(f"  {unmapped} distinct book strings were auto-derived (not in KNOWN_SOURCES)")


if __name__ == "__main__":
    main()
