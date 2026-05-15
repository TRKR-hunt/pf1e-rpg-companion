#!/usr/bin/env python3
"""
d20pfsrd trait scraper for the PF1e RPG Companion App system build.

Approach:
  - The /traits/ index page groups every PF1e trait under H3 category
    headings (Combat / Faith / Magic / Mount / Social / Race / Regional /
    Religion). Each H3 is followed by a single <div> containing all of
    that category's trait detail-page links.
  - We extract (name, url, category) tuples from the index, then fetch
    each trait page (rate-limited, cached) and parse the prose body.

Trait detail pages on d20pfsrd are simple compared to feat pages:
  - Breadcrumb: Home > Traits > <Category> > <Name>
  - One or more sections: "Benefits:" or "Benefit:" plus optionally
    "Prerequisites:", "Special:", "Note:"
  - Closing "Section 15: Copyright Notice" boilerplate.

Politeness:
  - 2-second rate limit between fetches (cached pages are free).
  - Browser User-Agent (d20pfsrd's nginx 410s non-browser UAs).

Usage:
    python scrape_traits.py                 # scrape all categories
    python scrape_traits.py --limit 5       # smoke-test with N traits
    python scrape_traits.py --category combat
"""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
      "PF1e-RPGCompanion-Builder/0.1")
BASE = "https://www.d20pfsrd.com"
INDEX_URL = f"{BASE}/traits/"
CACHE_DIR = Path(__file__).parent / ".cache"
OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"
RATE_LIMIT_SECONDS = 2.0

# Map d20pfsrd's "<X> Traits" heading text to our trait_categories enum id.
CATEGORY_FROM_HEADING = {
    "combat traits": "combat",
    "faith traits": "faith",
    "magic traits": "magic",
    "mount traits": "mount",
    "social traits": "social",
    "race traits": "race",
    "regional traits": "regional",
    "religion traits": "religion",
    "campaign traits": "campaign",
}


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def fetch(url: str) -> str:
    CACHE_DIR.mkdir(exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.html"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    time.sleep(RATE_LIMIT_SECONDS)
    print(f"  GET {url}")
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    cache_file.write_text(resp.text, encoding="utf-8")
    return resp.text


def find_all_trait_links() -> list[tuple[str, str, str]]:
    """Return (name, detail_url, category_id) for every trait on the index."""
    html = fetch(INDEX_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    out: list[tuple[str, str, str]] = []
    seen_urls: set[str] = set()
    for h3 in content.find_all("h3"):
        heading_text = h3.get_text(" ", strip=True).lower()
        category = CATEGORY_FROM_HEADING.get(heading_text)
        if category is None:
            continue
        # The trait list lives in the next <div> sibling.
        nxt = h3.find_next_sibling()
        while nxt is not None and nxt.name != "div":
            nxt = nxt.find_next_sibling()
        if nxt is None:
            continue
        for a in nxt.find_all("a", href=True):
            name = a.get_text(strip=True)
            href = urljoin(INDEX_URL, a["href"])
            if not name or len(name) > 120:
                continue
            if "/traits/" not in href:
                continue
            path = urlparse(href).path
            # Skip category index pages and category-listing/filter pages.
            if path.rstrip("/").endswith("-traits") or path.rstrip("/") == "/traits":
                continue
            if "#" in href:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            out.append((name, href, category))
    return out


# Field labels d20pfsrd uses on trait detail pages. Pages vary:
#   "Benefits: ..."         (inline, with colon)
#   "Benefit(s)\n..."       (label on its own line, may have parenthetical-s)
#   "Benefits\nText..."     (label on its own line, no colon)
# Regex below requires the label to be standalone (preceded by newline or
# start-of-body) so we don't match the word "benefit" mid-prose. Trailing
# colon and parenthetical-s both optional.
_FIELD_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(Benefits?|Prerequisites?|Special|Note|Normal)(?:\(s\))?\s*:?\s*",
    re.IGNORECASE,
)


def _strip_trailers(body: str) -> str:
    """Drop d20pfsrd boilerplate from the end of a trait body."""
    # "Section 15: Copyright Notice" trailer.
    cut = re.search(r"\n?Section 15\s*:", body, re.IGNORECASE)
    if cut:
        body = body[: cut.start()]
    return body.strip()


def _split_into_fields(body: str) -> dict[str, str]:
    """Walk the body text looking for `Label:` markers; split content
    between them. Strips the Section 15 copyright trailer first."""
    body = _strip_trailers(body)
    matches = list(_FIELD_LABEL_RE.finditer(body))
    if not matches:
        return {"description": body}
    fields: dict[str, str] = {}
    for i, m in enumerate(matches):
        # "Benefits" / "Benefit" / "Benefit(s)" all normalize to "benefit"
        label = m.group(1).lower().rstrip("s")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        if label in fields:
            fields[label] = fields[label] + "\n\n" + chunk
        else:
            fields[label] = chunk
    return fields


def _url_slug(url: str) -> str:
    """Derive a unique slug from a trait detail URL.

    d20pfsrd disambiguates same-named traits (Bandit, Demon Slayer,
    Resilient...) via the URL path, not the display name. Using
    slugify(name) collides; using the URL's last path segment doesn't.
    """
    path = urlparse(url).path.rstrip("/")
    last = path.rsplit("/", 1)[-1]
    return slugify(last)


def _collapse_inline_newlines(text: str) -> str:
    """d20pfsrd's inline <a> tags get rendered as their own text nodes by
    BeautifulSoup's `get_text("\\n")`, producing mid-sentence newlines
    like 'Once per day as a\\nfree action\\n, you can take 10'. Collapse
    single newlines (mid-sentence) to spaces while preserving paragraph
    breaks (double newlines)."""
    # Protect paragraph breaks with a placeholder.
    PARA = " "
    text = re.sub(r"\n{2,}", PARA, text)
    # Collapse remaining single newlines + surrounding whitespace to one space.
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    # Restore paragraph breaks.
    text = text.replace(PARA, "\n\n")
    # Tidy double spaces and stray spaces before punctuation.
    text = re.sub(r"  +", " ", text)
    text = re.sub(r" +([,.;:!?])", r"\1", text)
    return text.strip()


def parse_trait_page(name: str, url: str, category: str) -> dict | None:
    import scrape_lib
    html = fetch(url)
    # Extract source from the Section 15 OGL footer BEFORE stripping it
    # for body parsing.
    source_id, _book_raw = scrape_lib.extract_section_15_source(html)

    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()
    body = content.get_text("\n", strip=True)
    # Drop the breadcrumb (Home > Traits > <Category> > <Name>) if present.
    body = re.sub(r"^\s*Home\b[\s>\n]+Traits\b[\s>\n]+[^\n]+\n", "", body)
    # Drop the page <h1> title if it duplicates the trait name.
    body = re.sub(rf"^\s*{re.escape(name)}\s*\n+", "", body, count=1)

    fields = _split_into_fields(body)

    benefit = _collapse_inline_newlines(fields.get("benefit", ""))
    prereq = _collapse_inline_newlines(fields.get("prerequisite", ""))
    special = _collapse_inline_newlines(fields.get("special", ""))
    description_parts: list[str] = []
    if benefit:
        description_parts.append(f"**Benefit:** {benefit}")
    if special:
        description_parts.append(f"**Special:** {special}")
    description = "\n\n".join(description_parts)
    if not description:
        # Fallback to whatever prose we got after the breadcrumb.
        description = _collapse_inline_newlines(body.strip())
    description = description[:4000]

    inst_id = f"{_url_slug(url)}__crb_"
    return {
        "resource_id": "trait",
        "stats": {
            "id": inst_id,
            "name": {"value": name},
            "source": {"value": source_id},
            "trait_category": {"value": category},
            "prerequisites": {"value": prereq[:400]},
            "description": {"value": description},
            "is_basic": {"value": category in ("combat", "faith", "magic", "social")},
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default=None, choices=list(CATEGORY_FROM_HEADING.values()),
                    help="Restrict to one category (default: all).")
    ap.add_argument("--limit", type=int, default=0, help="Stop after N traits (debug).")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    import scrape_lib
    scrape_lib.reset_source_trackers()
    print(f"Indexing traits from {INDEX_URL}")
    triples = find_all_trait_links()
    if args.category:
        triples = [t for t in triples if t[2] == args.category]
    by_cat: dict[str, int] = {}
    for _, _, c in triples:
        by_cat[c] = by_cat.get(c, 0) + 1
    print(f"Found {len(triples)} traits across {len(by_cat)} categories:")
    for cat, n in sorted(by_cat.items()):
        print(f"  {cat}: {n}")

    if args.limit:
        triples = triples[: args.limit]

    # ID-level disambiguation: when two trait detail URLs produce the
    # same final-segment slug, prefix the id with the category. Same-cat
    # same-slug is also handled (uses category_slug regardless).
    slug_buckets: dict[str, list] = {}
    for n, u, c in triples:
        slug_buckets.setdefault(_url_slug(u), []).append((n, u, c))

    # NAME-level disambiguation: the bundled compiler derives the per-
    # resource output filename from the `name` stat. d20pfsrd has 13
    # trait name collisions (e.g. two regional "Bandit" traits, one
    # combat & one regional "Demon Slayer"). Without disambiguation the
    # compiler silently overwrites one .rpg file with the other. Compute
    # unique display names up-front and use those when emitting.
    import scrape_lib
    unique_names = scrape_lib.disambiguate_names(triples)

    written = 0
    errors = 0
    for (name, url, category), display_name in zip(triples, unique_names):
        try:
            trait = parse_trait_page(name, url, category)
            if not trait:
                continue
            base_slug = _url_slug(url)
            if len(slug_buckets[base_slug]) > 1:
                # ID-level disambiguation.
                trait["stats"]["id"] = f"{category}_{base_slug}__crb_"
            # Apply the unique display name (overrides the bare scraped name).
            trait["stats"]["name"]["value"] = display_name
            out_path = OUT_DIR / f"trait_{trait['stats']['id']}.rpg.json"
            out_path.write_text(json.dumps(trait, indent=2), encoding="utf-8")
            written += 1
        except Exception as e:
            errors += 1
            print(f"  ! {name} ({url}): {e}")

    print(f"\nDone: wrote {written} traits, {errors} errors")
    # Sanity: count unique compiler slugs of the names we just wrote.
    slug_count = len({scrape_lib.compiler_slug(dn) for dn in unique_names})
    print(f"Unique compiler-slug names: {slug_count} (expect == {written})")
    # Report source extraction results.
    print(f"\nSource attribution: {len(scrape_lib.seen_sources)} distinct ids")
    if scrape_lib.unknown_sources:
        print(f"Unknown / unmapped book strings ({len(scrape_lib.unknown_sources)} distinct):")
        for raw, n in sorted(scrape_lib.unknown_sources.items(), key=lambda kv: -kv[1])[:30]:
            print(f"  {n:4} {raw[:120]!r}")


if __name__ == "__main__":
    main()
