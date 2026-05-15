#!/usr/bin/env python3
"""d20pfsrd equipment scraper — full mechanical parse.

Parses the d20pfsrd Weapons / Armor / Goods-and-Services tables into the
mechanically-modeled `weapon`, `armor`, and `item` resource types.

- Weapons: 18 grouped tables → weapon stats (cost_gp, damage,
  damage_small, critical, range_increment_ft, weight_lb, damage_type,
  special, category).
- Armor: grouped sub-tables → armor stats (cost_gp, armor_bonus,
  max_dex_bonus, armor_check_penalty, arcane_spell_failure, speed,
  weight_lb, category/type).
- Goods & services → item stats (name, cost_gp via cost res, weight,
  description, type).

Curated guard: never overwrites a hand-authored weapon/armor that
already has populated mechanical fields (the 66 weapons / 18 armor).

Usage:
    python scrape_equipment.py --kind weapons --discover-only
    python scrape_equipment.py --kind weapons|armor|goods [--limit N]
    python scrape_equipment.py --kind all
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

WEAPONS_URL = f"{BASE}/equipment/weapons/"
ARMOR_URL = f"{BASE}/equipment/armor/"
GOODS_URL = f"{BASE}/equipment/goods-and-services/"

# d20pfsrd product code → our source id (best-effort; common PF1e codes).
PZO_SOURCE = {
    "PZO1110": "crb", "PZO1115": "apg", "PZO1118": "uc", "PZO1117": "um",
    "PZO1121": "arg", "PZO1129": "acg", "PZO1135": "ui",
    "PZO1140": "uw", "PZO1123": "ultimate_equipment",
    "PZO1124": "ultimate_equipment",
}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def clean_name(s: str) -> str:
    """Strip d20pfsrd footnote markers (* † ‡ § ¹²³ etc.) and trailing
    source tags from a scraped name. The compiler derives the per-resource
    output filename from `name`, and chars like '*' are illegal in Windows
    paths, so names must be filesystem-safe."""
    if not s:
        return s
    s = s.replace("—", "").strip()
    # Drop bracketed source tags like " [ APC ]" / " (PFU)".
    s = re.sub(r"\s*[\[(][A-Z0-9:.,\s/&-]{2,40}[\])]\s*$", "", s)
    # Drop footnote markers and other path-hostile punctuation.
    s = re.sub(r"[*†‡§¹²³⁴⁵#~^|\\<>:\"?]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .,;-")
    return s


def _num(s: str, *, gp: bool = False) -> int:
    """Parse '12 gp' / '8 lbs.' / '1,200 gp' → int. Em-dash/blank → 0."""
    if not s:
        return 0
    s = s.replace("—", "").replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return 0
    val = float(m.group(1))
    return int(round(val))


_DMG_TYPE_MAP = {
    "B": "bludgeoning", "P": "piercing", "S": "slashing",
    "B or P": "bludgeoning", "P or S": "piercing", "B or S": "bludgeoning",
    "B and P": "bludgeoning", "P and S": "piercing",
}


def _dmg_type(s: str) -> str:
    s = (s or "").replace("—", "").strip()
    return _DMG_TYPE_MAP.get(s, s.split(" or ")[0].split(" and ")[0].strip().lower()
                             and {"b": "bludgeoning", "p": "piercing",
                                  "s": "slashing"}.get(
                                      s[0].lower(), "") or "")


def _source_from_code(code: str) -> str:
    if not code:
        return "unknown"
    first = re.split(r"[ /]", code.strip())[0]
    return PZO_SOURCE.get(first, "unknown")


def _is_curated(out_path: Path, *, mech_keys: tuple) -> bool:
    """Skip overwriting an instance that already has populated mechanical
    stats (a hand-authored curated entry)."""
    if not out_path.exists():
        return False
    try:
        s = json.loads(out_path.read_text(encoding="utf-8")).get("stats", {})
        for k in mech_keys:
            v = s.get(k, {}).get("value")
            if isinstance(v, (int, float)) and v:
                return True
            if isinstance(v, str) and v.strip():
                return True
        return False
    except Exception:
        return False


# ----- weapons -----

def _weapon_category(group_header: str) -> str:
    """'(Simple) Light Melee' / '(Martial) Two-Handed' / '(Exotic)
    Ranged' → simple_light / martial_twoh / exotic_ranged."""
    g = group_header.lower()
    prof = ("exotic" if "exotic" in g else
            "martial" if "martial" in g else "simple")
    if "ranged" in g or "ammunition" in g:
        hand = "ranged"
    elif "two-hand" in g or "two hand" in g:
        hand = "twoh"
    elif "one-hand" in g or "one hand" in g:
        hand = "oneh"
    elif "light" in g:
        hand = "light"
    else:
        hand = "oneh"
    return f"{prof}_{hand}"


def scrape_weapons(limit: int = 0) -> int:
    html = scrape_lib.fetch(WEAPONS_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    written = 0
    for table in content.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        # The group header is the first row's first cell, e.g.
        # "(Simple) Light Melee Weapons" or a caption.
        cap = table.find("caption")
        header_txt = (cap.get_text(" ", strip=True) if cap else "") or \
            rows[0].get_text(" ", strip=True)
        # Locate the column header row (contains "Cost" and "Dmg (M)").
        hdr_idx = None
        for i, r in enumerate(rows):
            cells = [c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])]
            if any(c.startswith("Cost") for c in cells) and \
               any("Dmg (M)" in c for c in cells):
                hdr_idx = i
                break
        if hdr_idx is None:
            continue
        cols = [c.get_text(" ", strip=True) for c in
                rows[hdr_idx].find_all(["th", "td"])]
        def col(name):
            for j, c in enumerate(cols):
                if c.startswith(name):
                    return j
            return None
        ci = {k: col(k) for k in
              ("Cost", "Dmg (S)", "Dmg (M)", "Critical", "Range",
               "Weight", "Type", "Special", "Source")}
        category = _weapon_category(header_txt)
        for r in rows[hdr_idx + 1:]:
            tds = r.find_all(["td", "th"])
            if len(tds) < 5:
                continue
            vals = [t.get_text(" ", strip=True) for t in tds]
            name = clean_name(vals[0])
            if not name or name.lower().startswith(("(", "cost")):
                continue
            def g(key):
                idx = ci.get(key)
                return vals[idx] if idx is not None and idx < len(vals) else ""
            inst_id = f"{slugify(name)}__crb_"
            out_path = OUT_DIR / f"weapon_{inst_id}.rpg.json"
            if _is_curated(out_path, mech_keys=("damage", "cost_gp", "critical")):
                continue
            inst = {
                "resource_id": "weapon",
                "stats": {
                    "id": inst_id,
                    "name": {"value": name},
                    "source": {"value": _source_from_code(g("Source"))},
                    "category": {"value": category},
                    "cost_gp": {"value": _num(g("Cost"), gp=True)},
                    "damage_small": {"value": g("Dmg (S)").replace("—", "").strip()},
                    "damage": {"value": g("Dmg (M)").replace("—", "").strip()},
                    "critical": {"value": g("Critical").replace("—", "").strip()},
                    "range_increment_ft": {"value": _num(g("Range"))},
                    "weight_lb": {"value": _num(g("Weight"))},
                    "damage_type": {"value": _dmg_type(g("Type"))},
                    "special": {"value": g("Special").replace("—", "").strip()},
                },
            }
            out_path.write_text(json.dumps(inst, indent=2), encoding="utf-8")
            written += 1
            if limit and written >= limit:
                return written
    return written


# ----- armor -----

def _armor_category(group_header: str) -> str:
    g = group_header.lower()
    if "shield" in g:
        return "shield"
    if "heavy" in g:
        return "heavy"
    if "medium" in g:
        return "medium"
    if "light" in g:
        return "light"
    return "light"


def scrape_armor(limit: int = 0) -> int:
    html = scrape_lib.fetch(ARMOR_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    written = 0
    for table in content.find_all("table"):
        rows = table.find_all("tr")
        current_group = ""
        cols = None
        ci: dict = {}
        for r in rows:
            tds = r.find_all(["td", "th"])
            vals = [t.get_text(" ", strip=True) for t in tds]
            joined = " ".join(vals).lower()
            if len(vals) == 1 and ("armor" in joined or "shield" in joined):
                current_group = vals[0]
                continue
            if any(v.startswith("Cost") for v in vals) and \
               any("Armor" in v and "Bonus" in v for v in vals):
                cols = vals
                def col(name):
                    for j, c in enumerate(cols):
                        if name.lower() in c.lower():
                            return j
                    return None
                ci = {
                    "name": 0,
                    "cost": col("Cost"),
                    "bonus": col("Armor/Shield"),
                    "maxdex": col("Maximum Dex"),
                    "acp": col("Armor Check"),
                    "asf": col("Arcane Spell"),
                    "weight": col("Weight"),
                    "source": col("Source"),
                }
                continue
            if cols is None or len(vals) < 5:
                continue
            name = clean_name(vals[0])
            if not name or name.lower() in ("30 ft.", "20 ft.", "armor"):
                continue
            def g(key):
                idx = ci.get(key)
                return vals[idx] if idx is not None and idx < len(vals) else ""
            inst_id = f"{slugify(name)}__crb_"
            out_path = OUT_DIR / f"armor_{inst_id}.rpg.json"
            if _is_curated(out_path, mech_keys=("armor_bonus", "cost_gp")):
                continue
            inst = {
                "resource_id": "armor",
                "stats": {
                    "id": inst_id,
                    "name": {"value": name},
                    "source": {"value": _source_from_code(g("source"))},
                    "category": {"value": _armor_category(current_group)},
                    "type": {"value": _armor_category(current_group)},
                    "cost_gp": {"value": _num(g("cost"), gp=True)},
                    "armor_bonus": {"value": _num(g("bonus"))},
                    "base_ac": {"value": _num(g("bonus"))},
                    "max_dex_bonus": {"value": _num(g("maxdex")) or 99},
                    "armor_check_penalty": {"value": -abs(_num(g("acp")))},
                    "check_penalty": {"value": -abs(_num(g("acp")))},
                    "arcane_spell_failure": {"value": _num(g("asf"))},
                    "weight_lb": {"value": _num(g("weight"))},
                },
            }
            out_path.write_text(json.dumps(inst, indent=2), encoding="utf-8")
            written += 1
            if limit and written >= limit:
                return written
    return written


# ----- goods & services → item -----

def _goods_subpages() -> list[str]:
    from urllib.parse import urljoin, urlparse
    html = scrape_lib.fetch(GOODS_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    subs: list[str] = []
    seen: set[str] = set()
    for a in content.find_all("a", href=True):
        u = urljoin(GOODS_URL, a["href"])
        p = urlparse(u).path.rstrip("/")
        if "/goods-and-services/" in p and p != "/equipment/goods-and-services":
            if len([x for x in p.split("/") if x]) == 3 and u not in seen:
                seen.add(u)
                subs.append(u.split("#")[0])
    return subs


def scrape_goods(limit: int = 0) -> int:
    written = 0
    seen: set[str] = set()
    for sub in _goods_subpages():
        try:
            written += _scrape_goods_page(sub, seen, limit, written)
        except Exception as e:
            print(f"  ! goods subpage failed {sub}: {e}")
        if limit and written >= limit:
            break
    return written


def _scrape_goods_page(url: str, seen: set, limit: int, already: int) -> int:
    html = scrape_lib.fetch(url)
    src_id, _ = scrape_lib.extract_section_15_source(html)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    written = 0
    for table in content.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        # Find the header row: first row whose cells include an
        # Item/Name column and a Price/Cost column. (Row 0 is often a
        # group title like "Comfort and Shelter".)
        hdr_idx = None
        for i, r in enumerate(rows[:4]):
            cells = [c.get_text(" ", strip=True).lower()
                     for c in r.find_all(["th", "td"])]
            if cells and any(k in cells[0] for k in ("item", "name", "good",
                             "gear", "object", "substance", "tool",
                             "service", "container")) \
               and any(("price" in c or "cost" in c) for c in cells):
                hdr_idx = i
                break
        if hdr_idx is None:
            continue
        low = [c.get_text(" ", strip=True).lower()
               for c in rows[hdr_idx].find_all(["th", "td"])]
        cost_i = next((j for j, c in enumerate(low)
                       if "price" in c or "cost" in c), None)
        wt_i = next((j for j, c in enumerate(low) if "weight" in c), None)
        for r in rows[hdr_idx + 1:]:
            tds = r.find_all(["td", "th"])
            vals = [t.get_text(" ", strip=True) for t in tds]
            if len(vals) < 2:
                continue
            name = clean_name(vals[0])
            if not name or len(name) > 100 or name.lower() in ("item", "name"):
                continue
            # Skip numeric / non-item rows (sub-headers, measurements).
            if re.match(r"^[\d.,/×x\s-]+$", name) or len(name) < 2:
                continue
            slug = slugify(name)
            if slug in seen:
                continue
            seen.add(slug)
            cost_gp = _num(vals[cost_i], gp=True) if cost_i is not None and cost_i < len(vals) else 0
            wt = _num(vals[wt_i]) if wt_i is not None and wt_i < len(vals) else 0
            inst_id = f"{slug}__crb_"
            stats = {
                "id": inst_id,
                "name": {"value": name},
                "source": {"value": src_id},
                "type": {"value": "adventuring_gear"},
                "description": {"value": ""},
            }
            # cost / weight are resource<cost> / resource<weight> nested
            # resources, not flat ints. Only set when non-zero.
            if cost_gp:
                stats["cost"] = {"value": {
                    "resource_id": "cost",
                    "stats": {
                        "id": f"cost_{slug}",
                        "value": {"value": cost_gp},
                        "unit": {"value": "gold"},
                    },
                }}
            if wt:
                stats["weight"] = {"value": {
                    "resource_id": "weight",
                    "stats": {
                        "id": f"wt_{slug}",
                        "value": {"value": wt},
                        "unit": {"value": "pounds"},
                    },
                }}
            inst = {"resource_id": "item", "stats": stats}
            (OUT_DIR / f"item_{inst_id}.rpg.json").write_text(
                json.dumps(inst, indent=2), encoding="utf-8")
            written += 1
            if limit and written >= limit:
                return written
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True,
                    choices=["weapons", "armor", "goods", "all"])
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scrape_lib.reset_hard_stop()
    scrape_lib.reset_source_trackers()

    if args.discover_only:
        for kind, url in (("weapons", WEAPONS_URL), ("armor", ARMOR_URL),
                          ("goods", GOODS_URL)):
            html = scrape_lib.fetch(url)
            n = len(BeautifulSoup(html, "html.parser").find_all("table"))
            print(f"{kind}: {n} tables at {url}")
        return

    total = 0
    if args.kind in ("weapons", "all"):
        w = scrape_weapons(args.limit)
        print(f"weapons: wrote {w}")
        total += w
    if args.kind in ("armor", "all"):
        a = scrape_armor(args.limit)
        print(f"armor: wrote {a}")
        total += a
    if args.kind in ("goods", "all"):
        g = scrape_goods(args.limit)
        print(f"goods/items: wrote {g}")
        total += g
    print(f"\nDone: {total} equipment instances written.")


if __name__ == "__main__":
    main()
