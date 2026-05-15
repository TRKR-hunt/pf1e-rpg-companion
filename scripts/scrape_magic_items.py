#!/usr/bin/env python3
"""d20pfsrd magic-items scraper → `item` resource type (is_magic=true).

Two parse modes:
  - detail-page categories (rings, rods, staves, magic-weapons,
    magic-armor, wondrous-items): recursive discovery through alpha /
    slot sub-buckets, then parse each detail page.
  - table-row categories (potions, wands, scrolls): parse the rows.

Emits `item` instances. cost/weight are nested resource<cost> /
resource<weight> objects (matching the item schema).

Usage:
    python scrape_magic_items.py --kind <cat> --discover-only
    python scrape_magic_items.py --kind <cat> [--limit N]
    python scrape_magic_items.py --kind all
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

# category → (root_url, item_type enum, parse_mode)
CATS = {
    "rings":         (f"{BASE}/magic-items/rings/", "worn", "detail"),
    "rods":          (f"{BASE}/magic-items/rods/", "held", "detail"),
    "staves":        (f"{BASE}/magic-items/staves/", "staff", "detail"),
    "magic-weapons": (f"{BASE}/magic-items/magic-weapons/", "weapon", "detail"),
    "magic-armor":   (f"{BASE}/magic-items/magic-armor/", "armor", "detail"),
    "wondrous-items": (f"{BASE}/magic-items/wondrous-items/", "worn", "detail"),
    "potions":       (f"{BASE}/magic-items/potions/", "potion", "table"),
    "wands":         (f"{BASE}/magic-items/wands/", "wand", "table"),
    "scrolls":       (f"{BASE}/magic-items/scrolls/", "scroll", "table"),
}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def clean_name(s: str) -> str:
    if not s:
        return s
    s = s.replace("—", "").strip()
    s = re.sub(r"\s*[\[(][A-Z0-9:.,\s/&-]{2,40}[\])]\s*$", "", s)
    s = re.sub(r"[*†‡§¹²³⁴⁵#~^|\\<>:\"?]", "", s)
    return re.sub(r"\s+", " ", s).strip(" .,;-")


def _canon(href: str) -> str:
    pr = urlparse(href)
    segs = [s.strip("-").lower() for s in pr.path.split("/")]
    np = "/".join(segs)
    if not np.endswith("/"):
        np += "/"
    return urlunparse(pr._replace(path=np, fragment="", query=""))


def _collapse(text: str) -> str:
    PARA = "␟"
    text = re.sub(r"\n{2,}", PARA, text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = text.replace(PARA, "\n\n")
    text = re.sub(r"  +", " ", text)
    return re.sub(r" +([,.;:!?])", r"\1", text).strip()


def _num(s: str) -> int:
    if not s:
        return 0
    m = re.search(r"([\d,]+(?:\.\d+)?)", s.replace(",", ""))
    return int(round(float(m.group(1)))) if m else 0


_ALPHA_RE = re.compile(r"^[a-z](?:-[a-z])?$")


def _is_index_tail(tail: str) -> bool:
    return bool(_ALPHA_RE.match(tail)) or tail.endswith("-items") \
        or tail.endswith("-armor") or tail.endswith("-weapons") \
        or tail in ("rings", "rods", "staves", "ioun-stones", "magic-items")


def discover_detail(root: str) -> dict[str, str]:
    """Recursive walk of a detail-page magic-item category."""
    prefix = urlparse(root).path.rstrip("/")
    out: dict[str, str] = {}
    visited: set[str] = set()
    queue = [root]
    while queue:
        u = queue.pop()
        if u in visited:
            continue
        visited.add(u)
        try:
            html = scrape_lib.fetch(u)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("div", id="article-content") or soup
        for a in content.find_all("a", href=True):
            href = _canon(urljoin(u, a["href"]))
            p = urlparse(href).path.rstrip("/")
            if not p.startswith(prefix + "/"):
                continue
            if "3rd-party" in p:
                continue
            segs = [s for s in p.split("/") if s]
            tail = segs[-1]
            name = a.get_text(" ", strip=True)
            low = name.lower()
            if low.startswith("go to ") or low in ("next", "previous", "back"):
                continue
            if _is_index_tail(tail):
                if href not in visited and p != prefix:
                    queue.append(href)
            elif len(segs) >= 3:
                cn = clean_name(name)
                if cn and len(cn) <= 120:
                    out.setdefault(href, cn)
    return out


def _slug_id(url: str) -> str:
    return slugify(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])


def _cost_block(stats: dict, slug: str, price_gp: int, wt: int) -> None:
    if price_gp:
        stats["cost"] = {"value": {"resource_id": "cost", "stats": {
            "id": f"cost_{slug}", "value": {"value": price_gp},
            "unit": {"value": "gold"}}}}
    if wt:
        stats["weight"] = {"value": {"resource_id": "weight", "stats": {
            "id": f"wt_{slug}", "value": {"value": wt},
            "unit": {"value": "pounds"}}}}


def parse_detail(name: str, url: str, item_type: str) -> dict | None:
    html = scrape_lib.fetch(url)
    src_id, _ = scrape_lib.extract_section_15_source(html)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    for t in content.find_all(["script", "style", "nav", "aside"]):
        t.decompose()
    body = content.get_text("\n", strip=True)
    body = re.sub(r"^\s*Home\s*(?:>\s*[^\n>]+\s*){1,6}", "", body,
                  count=1, flags=re.IGNORECASE)
    body = re.sub(r"^\s*Contents\b[^\n]*\n", "", body, count=1)
    cut = re.search(r"\n?Section 15\s*:", body, re.IGNORECASE)
    if cut:
        body = body[: cut.start()]
    # Price / Weight from the magic-item stat block.
    pm = re.search(r"Price\s+([\d,]+)\s*gp", body, re.IGNORECASE)
    wm = re.search(r"Weight\s+([\d,. ]+?)\s*lb", body, re.IGNORECASE)
    price = _num(pm.group(1)) if pm else 0
    wt = _num(wm.group(1)) if wm else 0
    desc = _collapse(body)[:8000]
    slug = _slug_id(url)
    stats = {
        "id": f"{slug}__crb_",
        "name": {"value": name},
        "source": {"value": src_id},
        "type": {"value": item_type},
        "is_magic": {"value": True},
        "description": {"value": desc},
    }
    _cost_block(stats, slug, price, wt)
    return {"resource_id": "item", "stats": stats}


def scrape_table_cat(root: str, item_type: str, limit: int) -> int:
    """potions/wands/scrolls: items live in tables (name + price rows)."""
    html = scrape_lib.fetch(root)
    src_id, _ = scrape_lib.extract_section_15_source(html)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    written = 0
    seen: set[str] = set()
    for table in content.find_all("table"):
        rows = table.find_all("tr")
        hdr_i = None
        for i, r in enumerate(rows[:4]):
            cells = [c.get_text(" ", strip=True).lower()
                     for c in r.find_all(["th", "td"])]
            if cells and any("price" in c or "cost" in c for c in cells) \
               and any(k in cells[0] for k in ("name", "item", "potion",
                       "wand", "scroll", "spell")):
                hdr_i = i
                break
        if hdr_i is None:
            continue
        low = [c.get_text(" ", strip=True).lower()
               for c in rows[hdr_i].find_all(["th", "td"])]
        ci = next((j for j, c in enumerate(low)
                   if "price" in c or "cost" in c), None)
        for r in rows[hdr_i + 1:]:
            vals = [t.get_text(" ", strip=True)
                    for t in r.find_all(["td", "th"])]
            if len(vals) < 2:
                continue
            nm = clean_name(vals[0])
            if not nm or len(nm) < 2 or re.match(r"^[\d.,/×x\s-]+$", nm):
                continue
            slug = slugify(nm)
            if slug in seen:
                continue
            seen.add(slug)
            price = _num(vals[ci]) if ci is not None and ci < len(vals) else 0
            stats = {
                "id": f"{slug}__crb_",
                "name": {"value": nm},
                "source": {"value": src_id},
                "type": {"value": item_type},
                "is_magic": {"value": True},
                "description": {"value": ""},
            }
            _cost_block(stats, slug, price, 0)
            (OUT_DIR / f"item_{slug}__crb_.rpg.json").write_text(
                json.dumps({"resource_id": "item", "stats": stats}, indent=2),
                encoding="utf-8")
            written += 1
            if limit and written >= limit:
                return written
    return written


def _is_curated(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return bool(d.get("stats", {}).get("effects", {}).get("value"))
    except Exception:
        return False


def scrape_detail_cat(root: str, item_type: str, limit: int) -> int:
    found = discover_detail(root)
    items = sorted(found.items())
    if limit:
        items = items[:limit]
    triples = [(nm, u, None) for u, nm in items]
    uniq = scrape_lib.disambiguate_names(triples)

    def task(pair):
        (url, nm), disp = pair
        e = parse_detail(nm, url, item_type)
        if not e:
            return None
        e["stats"]["name"]["value"] = disp
        op = OUT_DIR / f"item_{e['stats']['id']}.rpg.json"
        if _is_curated(op):
            return None
        op.write_text(json.dumps(e, indent=2), encoding="utf-8")
        return op.name

    res = scrape_lib.parallel_map(list(zip(items, uniq)), task,
                                  label="magic-item")
    return sum(1 for r in res if r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True,
                    choices=list(CATS) + ["all"])
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scrape_lib.reset_hard_stop()
    scrape_lib.reset_source_trackers()

    kinds = list(CATS) if args.kind == "all" else [args.kind]
    total = 0
    for k in kinds:
        root, itype, mode = CATS[k]
        if args.discover_only:
            if mode == "detail":
                n = len(discover_detail(root))
            else:
                n = -1
            print(f"{k} [{mode}]: {n} detail URLs")
            continue
        if mode == "detail":
            w = scrape_detail_cat(root, itype, args.limit)
        else:
            w = scrape_table_cat(root, itype, args.limit)
        print(f"{k}: wrote {w}")
        total += w
    if not args.discover_only:
        print(f"\nDone: {total} magic-item instances. "
              f"source ids={len(scrape_lib.seen_sources)} "
              f"no-s15={scrape_lib.unknown_sources.get('__no_section_15__',0)}")


if __name__ == "__main__":
    main()
