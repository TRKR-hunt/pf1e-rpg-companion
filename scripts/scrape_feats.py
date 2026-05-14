#!/usr/bin/env python3
"""
d20pfsrd feat scraper for the Pathfinder 1e RPG Companion App system build.

Politeness:
  - 1 request per 2 seconds (configurable)
  - Identifies itself with a clear UA
  - Caches every page so repeats are free
  - Respects robots.txt (check before running)

Output: writes one .rpg.json per feat into ../resource_instances/.

Run from this scripts/ directory. Run once per category, e.g.:
    python scrape_feats.py --category combat
    python scrape_feats.py --category general
    python scrape_feats.py --category metamagic
    python scrape_feats.py --category item-creation
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

UA = "PF1e-RPGCompanion-Builder/0.1 (https://github.com/your-username/pf1e-rpg-companion)"
BASE = "https://www.d20pfsrd.com"
CACHE_DIR = Path(__file__).parent / ".cache"
OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"
RATE_LIMIT_SECONDS = 2.0

CATEGORY_INDEX = {
    "combat": f"{BASE}/feats/combat-feats/",
    "general": f"{BASE}/feats/general-feats/",
    "metamagic": f"{BASE}/feats/metamagic-feats/",
    "item-creation": f"{BASE}/feats/item-creation-feats/",
    "racial": f"{BASE}/feats/racial-feats/",
}


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def fetch(url: str) -> str:
    """Polite GET with on-disk cache."""
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


def find_feat_links(index_url: str) -> list[tuple[str, str]]:
    """Pull (name, url) pairs from a feat-category index page."""
    html = fetch(index_url)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    links = []
    seen = set()
    for a in content.find_all("a", href=True):
        href = urljoin(index_url, a["href"])
        # Only feat detail pages on d20pfsrd
        if not href.startswith(f"{BASE}/feats/"):
            continue
        # Skip the category index itself and known non-feat anchors
        path = urlparse(href).path
        if path.rstrip("/") == urlparse(index_url).path.rstrip("/"):
            continue
        if path.endswith("-feats/") or "/tools/" in path or "#" in href:
            continue
        name = a.get_text(strip=True)
        if not name or len(name) > 80:
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append((name, href))
    return links


def parse_feat_page(name: str, url: str, category: str) -> dict | None:
    """Parse a d20pfsrd feat detail page into our schema."""
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup

    # Strip script/style/nav noise
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()

    text = content.get_text("\n", strip=True)

    # Common section markers in d20pfsrd feat pages
    fields = {
        "prerequisites": _extract_field(text, "Prerequisite", "Benefit"),
        "benefit": _extract_field(text, "Benefit", "Normal"),
        "normal": _extract_field(text, "Normal", "Special"),
        "special": _extract_field(text, "Special", None),
    }

    descr_parts = []
    for label, value in fields.items():
        if value:
            descr_parts.append(f"**{label.title()}:** {value}")
    description = "\n\n".join(descr_parts) or text[:2000]

    feat_id = f"feat_{slugify(name)}__crb_"
    return {
        "resource_id": "feat",
        "stats": {
            "id": {"value": feat_id},
            "name": {"value": name},
            "source": {"value": "crb"},
            "type": {"value": category},
            "traits": {"value": category},
            "prerequisites": {"value": fields["prerequisites"] or ""},
            "description": {"value": description},
            "source_url": {"value": url},
            "effects": {"value": []},
        },
    }


def _extract_field(text: str, start_label: str, end_label: str | None) -> str:
    """Extract content between two section labels in the rendered text."""
    pattern_start = re.compile(rf"\b{re.escape(start_label)}\s*:?\s*", re.IGNORECASE)
    m = pattern_start.search(text)
    if not m:
        return ""
    start = m.end()
    if end_label:
        m2 = re.search(rf"\b{re.escape(end_label)}\s*:", text[start:], re.IGNORECASE)
        end = start + m2.start() if m2 else len(text)
    else:
        end = len(text)
    return text[start:end].strip().split("\n")[0][:1500]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", required=True, choices=list(CATEGORY_INDEX.keys()))
    ap.add_argument("--limit", type=int, default=0, help="Stop after N feats (debug)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_url = CATEGORY_INDEX[args.category]
    print(f"Indexing {args.category} feats from {index_url}")
    links = find_feat_links(index_url)
    print(f"Found {len(links)} candidate feats")
    if args.limit:
        links = links[: args.limit]

    written = 0
    for name, url in links:
        try:
            feat = parse_feat_page(name, url, args.category)
            if not feat:
                continue
            out_path = OUT_DIR / f"{feat['stats']['id']['value']}.rpg.json"
            out_path.write_text(json.dumps(feat, indent=2), encoding="utf-8")
            written += 1
            print(f"  wrote {out_path.name}")
        except Exception as e:
            print(f"  ! {name} ({url}): {e}")

    print(f"\nDone: wrote {written} feats for category={args.category}")


if __name__ == "__main__":
    main()
