#!/usr/bin/env python3
"""d20pfsrd spell scraper for the PF1e RPG Companion App system build.

Discovers every Players-side class spell list from
/magic/spell-lists-and-domains/, walks each list to collect (spell, level,
class) triples, then fetches each unique spell detail page in parallel
via scrape_lib. Merges class lists into one instance per spell.

Usage:
    python scrape_spells.py --discover-only      # list class lists & counts
    python scrape_spells.py --limit 10           # smoke test
    python scrape_spells.py                      # full scrape
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
ROOT_URL = f"{BASE}/magic/spell-lists-and-domains/"
OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

# Class spell-list pages on d20pfsrd. The text→class_id mapping uses our
# canonical class ids; some d20pfsrd labels combine two classes (Cleric/
# Oracle share a list, Sorcerer/Wizard share a list).
CLASS_LISTS: dict[str, list[str]] = {
    "spell-lists-bard": ["bard"],
    "spell-lists-cleric": ["cleric", "oracle"],
    "spell-lists-druid": ["druid"],
    "spell-lists-paladin": ["paladin"],
    "spell-lists-ranger": ["ranger"],
    "spell-lists-sorcerer-and-wizard": ["sorcerer", "wizard"],
    "antipaladin-spell-list": ["antipaladin"],
    "formulae-lists-alchemist": ["alchemist"],
    "spell-lists-inquisitor": ["inquisitor"],
    "magus-spell-list": ["magus"],
    "spell-lists-summoner": ["summoner"],
    "spell-list-witch": ["witch"],
    "bloodrager": ["bloodrager"],
    "shaman": ["shaman"],
    "medium": ["medium"],
    "mesmerist": ["mesmerist"],
    "occultist": ["occultist"],
    "psychic": ["psychic"],
    "spiritualist": ["spiritualist"],
    "spell-lists-unchained-summoner": ["unchained_summoner"],
}


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _canonicalize_href(href: str) -> str:
    """Trailing-slash, lowercase, dash-trim per-segment. Collapses typo dupes."""
    parsed = urlparse(href)
    segs = [s.strip("-").lower() for s in parsed.path.split("/")]
    new_path = "/".join(segs)
    if not new_path.endswith("/"):
        new_path += "/"
    return urlunparse(parsed._replace(path=new_path, fragment=""))


def _url_slug(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    last = path.rsplit("/", 1)[-1]
    return slugify(last)


def _url_path_slug(url: str, root: str = "/magic/") -> str:
    path = urlparse(url).path.rstrip("/")
    if path.startswith(root):
        path = path[len(root):]
    return slugify(path)


def _collapse_inline_newlines(text: str) -> str:
    """Same fix used in the trait/feat scrapers."""
    PARA = "␟"
    text = re.sub(r"\n{2,}", PARA, text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = text.replace(PARA, "\n\n")
    text = re.sub(r"  +", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    return text.strip()


# ---------- discovery ----------

def discover_class_list_urls() -> dict[str, list[str]]:
    """Return {class_list_url: [class_ids]}."""
    html = scrape_lib.fetch(ROOT_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    out: dict[str, list[str]] = {}
    for a in content.find_all("a", href=True):
        href = _canonicalize_href(urljoin(ROOT_URL, a["href"]))
        path = urlparse(href).path.rstrip("/")
        if not path.startswith("/magic/spell-lists-and-domains"):
            continue
        if path == "/magic/spell-lists-and-domains":
            continue
        tail = path.rsplit("/", 1)[-1]
        cls = CLASS_LISTS.get(tail)
        if cls:
            out[href] = cls
    return out


_LEVEL_MARKER_RE = re.compile(
    r"\b(\d+)\s*(?:st|nd|rd|th)?[\s\-]*Level\b",
    re.IGNORECASE,
)


def find_spell_links(list_url: str, class_ids: list[str]) -> list[tuple[str, str, int]]:
    """Walk every <table> on the class master page; map each to a
    level via its <caption>; emit (spell_name, url, level) for each
    /magic/all-spells/ link inside that table's body.

    d20pfsrd renders each class spell list as one HTML document
    containing N tables, each captioned like '0-Level Wizard Spells
    (Cantrips)' or '3rd-Level Wizard Spells'. Third-party tables are
    captioned with 'Third Party' and skipped."""
    html = scrape_lib.fetch(list_url)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    out: list[tuple[str, str, int]] = []
    seen_on_class: set[str] = set()
    for table in content.find_all("table"):
        caption = table.find("caption")
        if caption is None:
            continue
        cap_text = caption.get_text(" ", strip=True)
        cap_low = cap_text.lower()
        if "third party" in cap_low or "3rd party" in cap_low:
            continue
        # Extract level from the caption.
        level: int | None = None
        if "cantrip" in cap_low or cap_low.startswith("0-level") or cap_low.startswith("0th"):
            level = 0
        else:
            m = _LEVEL_MARKER_RE.search(cap_text)
            if m:
                lvl = int(m.group(1))
                if 0 <= lvl <= 9:
                    level = lvl
        if level is None:
            continue
        # Collect spell links inside the table body.
        for a in table.find_all("a", href=True):
            href = _canonicalize_href(urljoin(list_url, a["href"]))
            path = urlparse(href).path.rstrip("/")
            if "/magic/all-spells/" not in path:
                continue
            segs = [s for s in path.split("/") if s]
            if len(segs) < 4:
                continue
            name = a.get_text(" ", strip=True)
            if not name or len(name) > 80:
                continue
            if href in seen_on_class:
                continue
            seen_on_class.add(href)
            out.append((name, href, level))
    return out


def discover_all_spells() -> dict[str, dict]:
    """Aggregate every Players-side spell URL into {url: {name, level, classes}}.

    Same URL referenced from multiple class lists merges into one entry
    with classes accumulated."""
    class_lists = discover_class_list_urls()
    all_spells: dict[str, dict] = {}
    for list_url, class_ids in class_lists.items():
        for name, url, level in find_spell_links(list_url, class_ids):
            entry = all_spells.setdefault(url, {
                "name": name,
                "level": level,
                "classes": set(),
            })
            for c in class_ids:
                entry["classes"].add(c)
            # Lowest level seen wins (some lists list a spell at higher
            # level under a sub-domain — keep the canonical baseline).
            if level < entry["level"]:
                entry["level"] = level
    return all_spells


# ---------- parsing ----------

# d20pfsrd's spell pages render each field as a label-line followed by
# value-line(s), separated by `<br>`/newlines (no colon). e.g.:
#
#   Casting Time
#   1 standard action
#   Components
#   V, S, M/DF (piece of seaweed)
#   Range
#   touch
#
# We walk the text line-by-line, treat known field labels as section
# starts, accumulate subsequent non-label lines as the value.
_FIELD_LABELS_CANON = [
    "School", "Level", "Casting Time", "Components", "Range",
    "Area", "Target", "Targets", "Duration", "Saving Throw",
    "Spell Resistance", "Effect", "Description",
]
# Lookup: lowercased label -> canonical lowercased key for the fields dict.
_LABEL_LOOKUP = {l.lower(): l.lower().replace(" ", "_") for l in _FIELD_LABELS_CANON}
# Also include the section-header noise lines d20pfsrd emits.
_SECTION_HEADERS = {"casting", "effect", "description"}


def _parse_spell_fields(text: str) -> dict[str, str]:
    """Walk d20pfsrd's spell body text; produce {field_key: value}."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    fields: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw in lines:
        low = raw.lower().rstrip(":")
        # Skip the section-header noise (CASTING / EFFECT / DESCRIPTION).
        if low in _SECTION_HEADERS:
            # The "Description" header starts the description section.
            if low == "description":
                current_key = "description"
                fields.setdefault(current_key, [])
            else:
                current_key = None
            continue
        if low in _LABEL_LOOKUP:
            current_key = _LABEL_LOOKUP[low]
            fields.setdefault(current_key, [])
            continue
        if current_key is not None:
            fields[current_key].append(raw)
    return {k: " ".join(v).strip() for k, v in fields.items()}


def parse_spell_page(name: str, url: str, level: int, classes: list[str]) -> dict | None:
    html = scrape_lib.fetch(url)
    source_id, _book_raw = scrape_lib.extract_section_15_source(html)

    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()
    text = content.get_text("\n", strip=True)

    fields = _parse_spell_fields(text)

    # Description: prefer the explicit "Description" section if parsed;
    # else fall back to the body tail.
    description = fields.pop("description", "")
    if not description:
        descr_idx = text.lower().rfind("description")
        description = text[descr_idx + len("description"):] if descr_idx > 0 else text
    description = _collapse_inline_newlines(description.strip())[:4000]

    # School: d20pfsrd repeats the School field 2-3 times on some pages,
    # accumulating to "transmutation ; transmutation ; transmutation".
    # Also uses subschool/descriptor decoration: "conjuration (creation)
    # [acid]". Reduce to the canonical first single school token.
    school_raw = fields.get("school", "")
    school = school_raw.split("(", 1)[0].split("[", 1)[0]
    # Split on any separator and take the first valid school keyword.
    school_tokens = re.split(r"[;:,]", school)
    school = school_tokens[0].strip().lower() if school_tokens else ""
    if not school:
        school = "abjuration"  # safe default; schema requires non-empty

    level_id = f"spell_level_{level}"
    # Stable id uses URL final segment (URL is unique per spell).
    inst_id = f"{_url_slug(url)}__crb_"
    return {
        "resource_id": "spell",
        "stats": {
            "id": inst_id,
            "name": {"value": name},
            "source": {"value": source_id},
            "level": {"value": level_id},
            "school": {"value": school},
            "classes": {"value": sorted(classes)},
            "casting_time": {"value": fields.get("casting_time", "")},
            "components": {"value": fields.get("components", "")},
            "range": {"value": fields.get("range", "")},
            "area": {"value": fields.get("area", "")
                              or fields.get("target", "")
                              or fields.get("targets", "")
                              or fields.get("effect", "")},
            "duration": {"value": fields.get("duration", "")},
            "saving_throw": {"value": fields.get("saving_throw", "").strip(";,. ")},
            "spell_resistance": {"value": (fields.get("spell_resistance", "").strip(";,. ") or "no")},
            "description": {"value": description},
        },
    }


def _is_curated(out_path: Path) -> bool:
    """Skip writing if the existing file has populated effects (real mechanics)."""
    if not out_path.exists():
        return False
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        eff = data.get("stats", {}).get("effects", {}).get("value", [])
        return bool(eff)
    except Exception:
        return False


def write_spell(name: str, url: str, level: int, classes: list[str],
                display_name: str, slug_buckets: dict) -> str | None:
    spell = parse_spell_page(name, url, level, classes)
    if not spell:
        return None
    base_slug = _url_slug(url)
    # ID disambiguation: fall back to full-path slug when URLs share a tail.
    if len(slug_buckets.get(base_slug, [])) > 1:
        spell["stats"]["id"] = f"{_url_path_slug(url)}__crb_"
    spell["stats"]["name"]["value"] = display_name
    out_path = OUT_DIR / f"spell_{spell['stats']['id']}.rpg.json"
    if _is_curated(out_path):
        return None
    out_path.write_text(json.dumps(spell, indent=2), encoding="utf-8")
    return out_path.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Discovering class spell lists from {ROOT_URL}")
    class_lists = discover_class_list_urls()
    print(f"Found {len(class_lists)} class spell-list pages.")

    all_spells = discover_all_spells()
    print(f"\nTotal unique spell URLs: {len(all_spells)}")
    # Per-class count + per-level distribution.
    by_class: dict[str, int] = {}
    by_level: dict[int, int] = {}
    for v in all_spells.values():
        for c in v["classes"]:
            by_class[c] = by_class.get(c, 0) + 1
        by_level[v["level"]] = by_level.get(v["level"], 0) + 1
    print("Per class:")
    for c, n in sorted(by_class.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")
    print("Per level (canonical):")
    for lvl in sorted(by_level):
        print(f"  spell_level_{lvl}: {by_level[lvl]}")

    if args.discover_only:
        return

    items = sorted(all_spells.items())  # deterministic by URL
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
        return write_spell(meta["name"], url, meta["level"],
                           sorted(meta["classes"]),
                           display_name, slug_buckets)

    print(f"\nScraping {len(items)} spells with {scrape_lib.WORKERS} workers...")
    scrape_lib.reset_hard_stop()
    scrape_lib.reset_source_trackers()
    paired = list(zip(items, unique_names))
    results = scrape_lib.parallel_map(paired, task, label="spell")
    written = sum(1 for r in results if r)
    failed = sum(1 for r in results if r is None)
    print(f"\nDone: wrote {written} spells, {failed} failures/skips.")

    slug_count = len({scrape_lib.compiler_slug(dn) for dn in unique_names})
    print(f"Unique compiler-slug names: {slug_count} (expect == {written})")
    print(f"\nSource attribution: {len(scrape_lib.seen_sources)} distinct ids")
    if scrape_lib.unknown_sources:
        nosec15 = scrape_lib.unknown_sources.get("__no_section_15__", 0)
        unmapped = sum(1 for k in scrape_lib.unknown_sources if k != "__no_section_15__")
        print(f"  {nosec15} pages had no Section 15 footer (-> 'unknown')")
        print(f"  {unmapped} distinct book strings were auto-derived")


if __name__ == "__main__":
    main()
