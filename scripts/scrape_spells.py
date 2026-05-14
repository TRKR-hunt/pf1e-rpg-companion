#!/usr/bin/env python3
"""
d20pfsrd spell scraper.

Targets the master Sorcerer/Wizard list as a strong starting point because it
covers ~70% of the Core spell set. Run additional class lists to cover the rest
(cleric, druid, bard, paladin, ranger).

Usage:
    python scrape_spells.py --list sorcerer-wizard --max-level 6
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

UA = "PF1e-RPGCompanion-Builder/0.1"
BASE = "https://www.d20pfsrd.com"
CACHE_DIR = Path(__file__).parent / ".cache"
OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"
RATE_LIMIT_SECONDS = 2.0

SPELL_LISTS = {
    "sorcerer-wizard": f"{BASE}/magic/spell-lists-and-domains/spell-lists-sorcerer-and-wizard/",
    "cleric": f"{BASE}/magic/spell-lists-and-domains/spell-lists-cleric/",
    "druid": f"{BASE}/magic/spell-lists-and-domains/spell-lists-druid/",
    "bard": f"{BASE}/magic/spell-lists-and-domains/spell-lists-bard/",
    "paladin": f"{BASE}/magic/spell-lists-and-domains/spell-lists-paladin/",
    "ranger": f"{BASE}/magic/spell-lists-and-domains/spell-lists-ranger/",
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


def find_spell_links(list_url: str, max_level: int, class_name: str) -> list[tuple[str, str, int]]:
    """Pull (spell_name, url, spell_level) from a class spell list page."""
    html = fetch(list_url)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    out = []
    current_level = None
    for el in content.descendants:
        if getattr(el, "name", None) in ("h2", "h3", "h4"):
            txt = el.get_text(" ", strip=True).lower()
            m = re.search(r"(\d+)(?:st|nd|rd|th)[-\s]+level", txt)
            if m:
                current_level = int(m.group(1))
                continue
            if "cantrip" in txt or "0-level" in txt or "orisons" in txt:
                current_level = 0
                continue
        if getattr(el, "name", None) == "a" and current_level is not None and current_level <= max_level:
            href = el.get("href", "")
            if not href or "/magic/" not in href:
                continue
            href = urljoin(list_url, href)
            if "spell-lists" in href or "tools" in href or "#" in href:
                continue
            name = el.get_text(strip=True)
            if not name or len(name) > 80:
                continue
            out.append((name, href, current_level))
    # Dedupe by URL keeping first level seen
    seen = set()
    uniq = []
    for name, href, lvl in out:
        if href in seen:
            continue
        seen.add(href)
        uniq.append((name, href, lvl))
    return uniq


def parse_spell_page(name: str, url: str, spell_level: int, class_name: str) -> dict | None:
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    for tag in content.find_all(["script", "style", "nav", "aside"]):
        tag.decompose()
    text = content.get_text("\n", strip=True)

    fields = {}
    for label in ("School", "Level", "Casting Time", "Components", "Range",
                  "Area", "Target", "Targets", "Duration", "Saving Throw",
                  "Spell Resistance", "Effect"):
        fields[label.lower().replace(" ", "_")] = _grab(text, label)

    descr_idx = max(
        (text.lower().find("description"), text.lower().find("\n\ndescription")),
    )
    description = text[descr_idx:] if descr_idx > 0 else text
    description = description[:4000]

    spell_id = f"spell_{slugify(name)}__crb_"
    return {
        "resource_id": "spell",
        "stats": {
            "id": {"value": spell_id},
            "name": {"value": name},
            "source": {"value": "crb"},
            "level": {"value": spell_level},
            "school": {"value": fields.get("school", "")},
            "casting_time": {"value": fields.get("casting_time", "")},
            "components": {"value": fields.get("components", "")},
            "range": {"value": fields.get("range", "")},
            "area": {"value": fields.get("area", "") or fields.get("target", "") or fields.get("targets", "") or fields.get("effect", "")},
            "duration": {"value": fields.get("duration", "")},
            "saving_throw": {"value": fields.get("saving_throw", "")},
            "spell_resistance": {"value": fields.get("spell_resistance", "")},
            "classes": {"value": [class_name]},
            "description": {"value": description},
            "source_url": {"value": url},
        },
    }


def _grab(text: str, label: str) -> str:
    m = re.search(rf"\b{re.escape(label)}\s*:\s*(.+)", text)
    if not m:
        return ""
    return m.group(1).strip().split("\n")[0][:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, choices=list(SPELL_LISTS.keys()))
    ap.add_argument("--max-level", type=int, default=9)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    list_url = SPELL_LISTS[args.list]
    print(f"Indexing {args.list} spells (≤ level {args.max_level}) from {list_url}")
    links = find_spell_links(list_url, args.max_level, args.list)
    print(f"Found {len(links)} candidate spells")
    if args.limit:
        links = links[: args.limit]

    written = 0
    for name, url, lvl in links:
        try:
            spell = parse_spell_page(name, url, lvl, args.list)
            if not spell:
                continue
            out_path = OUT_DIR / f"{spell['stats']['id']['value']}.rpg.json"
            # If file already exists from a previous class list, merge the class
            if out_path.exists():
                existing = json.loads(out_path.read_text())
                cls = existing["stats"].setdefault("classes", {"value": []})
                if args.list not in cls["value"]:
                    cls["value"].append(args.list)
                out_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
            else:
                out_path.write_text(json.dumps(spell, indent=2), encoding="utf-8")
            written += 1
        except Exception as e:
            print(f"  ! {name} ({url}): {e}")

    print(f"\nDone: wrote/updated {written} spells from {args.list}")


if __name__ == "__main__":
    main()
