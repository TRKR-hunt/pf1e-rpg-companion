#!/usr/bin/env python3
"""d20pfsrd poisons + drugs → `item` resource type (type=alchemical).

Poisons: the single "Table: Poisons" on /gamemastering/afflictions/poison/
(~105 rows). Drugs: individual subpages under
/gamemastering/afflictions/drugs/<drug>/.

Player-adjacent consumables (alchemists/assassins/rogues use them).
Emitted as item, is_magic=false, type=alchemical, with a composed
description from the affliction columns and cost from Price.

Usage: python scrape_afflictions.py [--kind poisons|drugs|all] [--limit N]
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
POISON_URL = f"{BASE}/gamemastering/afflictions/poison/"
DRUGS_URL = f"{BASE}/gamemastering/afflictions/drugs/"

PZO_SOURCE = {
    "PZO1110": "crb", "PZO1115": "apg", "PZO1118": "uc", "PZO1117": "um",
    "PZO1121": "arg", "PZO1129": "acg", "PZO1135": "ui", "PZO1140": "uw",
    "PZO1123": "ultimate_equipment", "PZO1124": "ultimate_equipment",
}


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def clean_name(s: str) -> str:
    if not s:
        return s
    s = re.sub(r"\s*[\[(][A-Z0-9:.,\s/&-]{2,40}[\])]\s*$", "", s.strip())
    s = re.sub(r"[*†‡§¹²³⁴⁵#~^|\\<>:\"?]", "", s)
    return re.sub(r"\s+", " ", s).strip(" .,;-")


def _num(s: str) -> int:
    if not s:
        return 0
    m = re.search(r"([\d,]+)", s.replace(",", ""))
    return int(m.group(1)) if m else 0


def _src(code: str) -> str:
    if not code:
        return "unknown"
    return PZO_SOURCE.get(re.split(r"[ /]", code.strip())[0], "unknown")


def _cost_block(stats: dict, slug: str, gp: int) -> None:
    if gp:
        stats["cost"] = {"value": {"resource_id": "cost", "stats": {
            "id": f"cost_{slug}", "value": {"value": gp},
            "unit": {"value": "gold"}}}}


def scrape_poisons(limit: int = 0) -> int:
    html = scrape_lib.fetch(POISON_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    written = 0
    seen: set[str] = set()
    for table in content.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        hdr = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        low = [h.lower() for h in hdr]
        if not (low and low[0].startswith("poison")):
            continue
        idx = {h.lower(): j for j, h in enumerate(hdr)}

        def gi(*names):
            for n in names:
                for k, j in idx.items():
                    if n in k:
                        return j
            return None
        c_type = gi("type")
        c_dc = gi("fort dc", "dc")
        c_onset = gi("onset")
        c_freq = gi("frequency")
        c_eff = gi("effect")
        c_cure = gi("cure")
        c_price = gi("price")
        c_src = gi("source")
        for r in rows[1:]:
            vals = [t.get_text(" ", strip=True) for t in r.find_all(["td", "th"])]
            if len(vals) < 4:
                continue
            name = clean_name(vals[0])
            if not name or len(name) < 2:
                continue
            slug = slugify(name)
            if slug in seen:
                continue
            seen.add(slug)

            def g(i):
                return vals[i] if i is not None and i < len(vals) else ""
            parts = []
            for label, i in (("Type", c_type), ("Fort DC", c_dc),
                             ("Onset", c_onset), ("Frequency", c_freq),
                             ("Effect", c_eff), ("Cure", c_cure)):
                v = g(i).replace("—", "").strip()
                if v:
                    parts.append(f"**{label}:** {v}")
            stats = {
                "id": f"{slug}__crb_",
                "name": {"value": name},
                "source": {"value": _src(g(c_src))},
                "type": {"value": "alchemical"},
                "is_magic": {"value": False},
                "description": {"value": " ".join(parts)[:4000]},
            }
            _cost_block(stats, slug, _num(g(c_price)))
            (OUT_DIR / f"item_{slug}__crb_.rpg.json").write_text(
                json.dumps({"resource_id": "item", "stats": stats}, indent=2),
                encoding="utf-8")
            written += 1
            if limit and written >= limit:
                return written
    return written


def _canon(href: str) -> str:
    pr = urlparse(href)
    segs = [s.strip("-").lower() for s in pr.path.split("/")]
    np = "/".join(segs)
    if not np.endswith("/"):
        np += "/"
    return urlunparse(pr._replace(path=np, fragment="", query=""))


def _collapse(t: str) -> str:
    t = re.sub(r"\n{2,}", "␟", t)
    t = re.sub(r"[ \t]*\n[ \t]*", " ", t).replace("␟", "\n\n")
    return re.sub(r"  +", " ", t).strip()


def scrape_drugs(limit: int = 0) -> int:
    html = scrape_lib.fetch(DRUGS_URL)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="article-content") or soup
    links: dict[str, str] = {}
    for a in content.find_all("a", href=True):
        u = _canon(urljoin(DRUGS_URL, a["href"]))
        p = urlparse(u).path.rstrip("/")
        if "/afflictions/drugs/" in p and "3rd-party" not in p \
           and len([z for z in p.split("/") if z]) >= 4:
            nm = clean_name(a.get_text(" ", strip=True))
            if nm and len(nm) <= 80:
                links.setdefault(u, nm)
    items = sorted(links.items())
    if limit:
        items = items[:limit]
    triples = [(nm, u, None) for u, nm in items]
    uniq = scrape_lib.disambiguate_names(triples)

    def task(pair):
        (url, nm), disp = pair
        h = scrape_lib.fetch(url)
        sid, _ = scrape_lib.extract_section_15_source(h)
        s = BeautifulSoup(h, "html.parser")
        c = s.find("div", id="article-content") or s
        for t in c.find_all(["script", "style", "nav", "aside"]):
            t.decompose()
        body = c.get_text("\n", strip=True)
        body = re.sub(r"^\s*Home\s*(?:>\s*[^\n>]+\s*){1,6}", "", body,
                      count=1, flags=re.IGNORECASE)
        cut = re.search(r"\n?Section 15\s*:", body, re.IGNORECASE)
        if cut:
            body = body[: cut.start()]
        pm = re.search(r"Price\s+([\d,]+)\s*gp", body, re.IGNORECASE)
        slug = slugify(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
        stats = {
            "id": f"{slug}__crb_",
            "name": {"value": disp},
            "source": {"value": sid},
            "type": {"value": "alchemical"},
            "is_magic": {"value": False},
            "description": {"value": _collapse(body)[:4000]},
        }
        _cost_block(stats, slug, _num(pm.group(1)) if pm else 0)
        op = OUT_DIR / f"item_{slug}__crb_.rpg.json"
        op.write_text(json.dumps({"resource_id": "item", "stats": stats},
                                 indent=2), encoding="utf-8")
        return op.name

    res = scrape_lib.parallel_map(list(zip(items, uniq)), task, label="drug")
    return sum(1 for r in res if r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="all",
                    choices=["poisons", "drugs", "all"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scrape_lib.reset_hard_stop()
    scrape_lib.reset_source_trackers()
    total = 0
    if args.kind in ("poisons", "all"):
        p = scrape_poisons(args.limit)
        print(f"poisons: wrote {p}")
        total += p
    if args.kind in ("drugs", "all"):
        d = scrape_drugs(args.limit)
        print(f"drugs: wrote {d}")
        total += d
    print(f"\nDone: {total} affliction items.")


if __name__ == "__main__":
    main()
