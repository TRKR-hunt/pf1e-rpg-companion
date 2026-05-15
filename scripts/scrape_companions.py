#!/usr/bin/env python3
"""Animal-companion + familiar selection lists → compendium_entry
(category=companion_lore).

Lore/reference only — the mechanical `companion` type wraps a
`monster` resource and stays empty until Session D's bestiary lands.
This captures the *which creature can be a companion/familiar* lists
(name + size/terrain/special) as browsable reference.

Source pages:
  /classes/core-classes/druid/animal-companions/  (companion-list tables)
  /classes/core-classes/wizard/familiar/          (familiar-list table)
Mounts are not a separate catalogue in PF1e (cavalier/paladin mounts
are animal companions); no separate scrape.

Usage: python scrape_companions.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

import scrape_lib

BASE = "https://www.d20pfsrd.com"
OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"
PAGES = [
    (f"{BASE}/classes/core-classes/druid/animal-companions/", "animal companion"),
    (f"{BASE}/classes/core-classes/wizard/familiar/", "familiar"),
]


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def clean_name(s: str) -> str:
    s = re.sub(r"\s*[\[(][A-Z0-9:.,\s/&-]{2,40}[\])]\s*$", "", (s or "").strip())
    s = re.sub(r"[*†‡§¹²³⁴⁵#~^|\\<>:\"?]", "", s)
    return re.sub(r"\s+", " ", s).strip(" .,;-")


def scrape(limit: int = 0) -> int:
    written = 0
    seen: set[str] = set()
    for url, kind in PAGES:
        html = scrape_lib.fetch(url)
        src_id, _ = scrape_lib.extract_section_15_source(html)
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("div", id="article-content") or soup
        for table in content.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            hdr = [c.get_text(" ", strip=True) for c in
                   rows[0].find_all(["th", "td"])]
            low = [h.lower() for h in hdr]
            # Only the creature-selection tables (first col Name/Familiar);
            # skip the level-progression tables.
            if not low or not (low[0].startswith("name")
                               or low[0].startswith("familiar")):
                continue
            for r in rows[1:]:
                vals = [t.get_text(" ", strip=True)
                        for t in r.find_all(["td", "th"])]
                if len(vals) < 2:
                    continue
                name = clean_name(vals[0])
                if not name or len(name) < 2:
                    continue
                slug = slugify(name)
                if slug in seen:
                    continue
                seen.add(slug)
                parts = []
                for h, v in zip(hdr[1:], vals[1:]):
                    v = v.replace("—", "").strip()
                    if v and not h.lower().startswith("source"):
                        parts.append(f"**{h.strip()}:** {v}")
                desc = f"{kind.title()}. " + " ".join(parts)
                stats = {
                    "id": f"companion_lore_{slug}__crb_",
                    "name": {"value": name},
                    "source": {"value": src_id},
                    "category": {"value": "companion_lore"},
                    "prerequisites_text": {"value": ""},
                    "description": {"value": desc[:4000]},
                    "related_mechanical_resource_id": {"value": ""},
                }
                (OUT_DIR / f"compendium_entry_companion_lore_{slug}__crb_.rpg.json"
                 ).write_text(json.dumps(
                     {"resource_id": "compendium_entry", "stats": stats},
                     indent=2), encoding="utf-8")
                written += 1
                if limit and written >= limit:
                    return written
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scrape_lib.reset_hard_stop()
    scrape_lib.reset_source_trackers()
    n = scrape(args.limit)
    print(f"\nDone: {n} companion_lore entries.")


if __name__ == "__main__":
    main()
