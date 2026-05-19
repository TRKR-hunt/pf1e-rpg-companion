"""Faithful d20pfsrd lore re-scraper - discovery-driven.

Two phases:
  --build-index   crawl d20pfsrd index pages, save URL index
  --apply         match each instance to a URL, rewrite lore

Default --apply is DRY-RUN. Pass --write to commit.

Usage:
  pip install requests beautifulsoup4
  python scripts/scrape_d20pfsrd.py --build-index
  python scripts/scrape_d20pfsrd.py --apply --kind=race
  python scripts/scrape_d20pfsrd.py --apply --kind=race --write
  python scripts/scrape_d20pfsrd.py --apply --kind=all --write

Caches every fetched page in scripts/d20pfsrd_cache/ so re-runs are cheap.
"""
import argparse, hashlib, json, os, re, sys, time, urllib.parse, difflib
from pathlib import Path
from collections import defaultdict

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("requires: pip install requests beautifulsoup4", file=sys.stderr)
    sys.exit(1)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
INST_DIR = REPO / "pf1e" / "resource_instances"
INDEX_PATH = HERE / "d20pfsrd_url_index.json"
CACHE_DIR = HERE / "d20pfsrd_cache"
SENTINEL = "<!-- d20pfsrd:rewritten -->"
UA = "Mozilla/5.0 (pf1e-rpg-companion-app/1.0 lore-rewriter)"
MIN_PROSE = 250  # default
# Per-category overrides: traits and feats often have very short rules
# text (1-2 paragraphs) that legitimately falls below 250 chars but is
# the correct page content. Empirical: ~500 of 1239 traits and ~90 of
# 3151 feats hit the default cutoff while having real content.
MIN_PROSE_BY_KIND = {
    "trait": 100,
    "feat": 130,
}
BASE = "https://www.d20pfsrd.com"

# Verified against d20pfsrd live (2026-05-17). /races/featured-races/ is
# NOT a directory; the actual ARG featured races live under
# /races/other-races/featured-races/. /races/ itself lists all 7 core
# races so seeding from it is enough to reach them.
SEEDS = {
    "race": [f"{BASE}/races/",
             f"{BASE}/races/other-races/",
             f"{BASE}/races/other-races/featured-races/",
             f"{BASE}/races/other-races/more-races/",
             f"{BASE}/races/other-races/uncommon-races/"],
    "class": [f"{BASE}/classes/",
              f"{BASE}/classes/core-classes/",
              f"{BASE}/classes/base-classes/",
              f"{BASE}/classes/hybrid-classes/",
              f"{BASE}/classes/unchained-classes/",
              f"{BASE}/classes/alternate-classes/",
              f"{BASE}/alternative-rule-systems/paizo-rules-systems/occult-adventures/occult-classes/"],
    "prestige": [f"{BASE}/classes/prestige-classes/",
                 f"{BASE}/classes/prestige-classes/core-rulebook/",
                 f"{BASE}/classes/prestige-classes/apg/",
                 f"{BASE}/classes/prestige-classes/other-paizo/"],
    "archetype": [f"{BASE}/classes/",
                  f"{BASE}/classes/core-classes/",
                  f"{BASE}/classes/base-classes/",
                  f"{BASE}/classes/hybrid-classes/",
                  f"{BASE}/classes/unchained-classes/",
                  f"{BASE}/classes/alternate-classes/",
                  f"{BASE}/alternative-rule-systems/paizo-rules-systems/occult-adventures/occult-classes/"],
    "feat": [f"{BASE}/feats/", f"{BASE}/feats/general-feats/",
             f"{BASE}/feats/combat-feats/", f"{BASE}/feats/metamagic-feats/",
             f"{BASE}/feats/item-creation-feats/", f"{BASE}/feats/teamwork-feats/",
             f"{BASE}/feats/grit-feats/", f"{BASE}/feats/style-feats/",
             f"{BASE}/feats/racial-feats/", f"{BASE}/feats/story-feats/",
             f"{BASE}/feats/mythic-feats/", f"{BASE}/feats/critical-feats/",
             f"{BASE}/feats/panache-feats/", f"{BASE}/feats/performance-feats/",
             f"{BASE}/feats/animal-companion-feats/",
             f"{BASE}/feats/monster-feats/"],
    "trait": [f"{BASE}/traits/", f"{BASE}/traits/campaign-traits/",
              f"{BASE}/traits/combat-traits/", f"{BASE}/traits/faith-traits/",
              f"{BASE}/traits/magic-traits/", f"{BASE}/traits/race-traits/",
              f"{BASE}/traits/regional-traits/", f"{BASE}/traits/religion-traits/",
              f"{BASE}/traits/social-traits/", f"{BASE}/traits/equipment-traits/",
              f"{BASE}/traits/family-traits/"],
    "spell": [f"{BASE}/magic/all-spells/"],
}

PREFIX = {"race": "/races/", "class": "/classes/",
          "prestige": "/classes/prestige-classes/",
          # Archetypes live under each class's directory at
          # /classes/<group>/<class>/archetypes/... so the scope prefix
          # is /classes/ (constrained further by ENTRY_PATH_FRAGMENT).
          "archetype": "/classes/",
          "feat": "/feats/", "trait": "/traits/", "spell": "/magic/all-spells/"}

# Categories that have their content under an additional URL prefix
# besides PREFIX[cat]. Verified live URLs.
EXTRA_PREFIXES = {
    "class": ["/alternative-rule-systems/paizo-rules-systems/occult-adventures/occult-classes/"],
    "archetype": ["/alternative-rule-systems/paizo-rules-systems/occult-adventures/occult-classes/"],
}

# For categories whose entries live under per-parent subdirectories
# (e.g. archetypes at /classes/<group>/<class>/archetypes/<archetype>),
# entries must additionally contain one of these path fragments.
ENTRY_PATH_FRAGMENT = {
    "archetype": "/archetypes/",
}

# How many "hops" of recursion to perform starting from each seed. 0 =
# fetch seed only and take its direct out-links as candidates; do not
# recurse. This prevents the crawler from following bad relative links
# inside individual entry pages (the source of the 404 spam).
RECURSE_DEPTH = {
    "race": 0,        # all 5 seeds list every race directly
    "class": 0,       # all 7 seeds list every class directly
    "prestige": 1,    # /other-paizo/ has /a-b/, /c-d/, /e-h/ sub-indexes
    "archetype": 2,   # class index -> class page -> /archetypes/ index
    "feat": 0,        # subcategory seeds list every feat
    "trait": 0,       # subcategory seeds list every trait
    "spell": 1,       # /all-spells/ has per-letter sub-indexes
}

SKIP_PATS = [re.compile(p) for p in [
    r"/3rd-party-", r"/extras/", r"/wp-content/", r"/wp-admin/", r"#",
    r"\?", r"/feed/", r"/category/",
    r"\.(?:png|jpe?g|gif|svg|css|js|pdf|zip|xml)$",
    r"opengamingnetwork\.com", r"amazon\.com", r"/legal", r"/contact", r"/about"]]


def cache_path(url):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".html")


def fetch(url, session, force=False, rate=1.5, timeout=20):
    """Fetch a URL with disk caching. On 404 retry with slash flipped."""
    cp = cache_path(url)
    if not force and cp.exists():
        return cp.read_text(encoding="utf-8", errors="replace")
    try:
        r = session.get(url, timeout=timeout,
                        headers={"User-Agent": UA, "Accept": "text/html"})
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            raise
        alt = url[:-1] if url.endswith("/") else url + "/"
        r = session.get(alt, timeout=timeout,
                        headers={"User-Agent": UA, "Accept": "text/html"})
        r.raise_for_status()
    cp.write_text(r.text, encoding="utf-8")
    time.sleep(rate)
    return r.text


def norm_url(url):
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}/"


def _has_repeated_segment(path):
    """True if path has same non-trivial segment twice in a row (e.g.
    /races/core-races/core-races/elf/ — always wrong on d20pfsrd)."""
    segs = [s for s in path.split("/") if s]
    for i in range(len(segs) - 1):
        if segs[i] == segs[i + 1] and len(segs[i]) > 2:
            return True
    return False


def in_scope(url, cat):
    p = urllib.parse.urlparse(url)
    if p.netloc and p.netloc != urllib.parse.urlparse(BASE).netloc:
        return False
    prefixes = [PREFIX[cat]] + EXTRA_PREFIXES.get(cat, [])
    if not any(p.path.startswith(pre) for pre in prefixes):
        return False
    if _has_repeated_segment(p.path):
        return False
    for pat in SKIP_PATS:
        if pat.search(p.path):
            return False
    if p.path in prefixes:
        return False
    # For categories like archetype where entries live at deeper paths
    # under the same prefix, also enforce a required path fragment.
    frag = ENTRY_PATH_FRAGMENT.get(cat)
    if frag is not None and frag not in p.path:
        # still allow index pages to be crawled (they don't have the
        # fragment) — we DO want to recurse into class index pages so we
        # find the archetypes/ subdirs. Allow if the path is short
        # (≤4 segments under a category prefix) — these are typically
        # index pages.
        segs = [s for s in p.path.split("/") if s]
        return len(segs) <= 4
    return True


def page_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("main") or soup.find("article") or soup.body or soup
    out = set()
    for a in container.find_all("a", href=True):
        href = a["href"].strip()
        if href:
            out.add(norm_url(urllib.parse.urljoin(base_url, href)))
    return sorted(out)


def page_title(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    if soup.title and soup.title.string:
        return soup.title.string.split("|")[0].split("-")[0].strip()
    return ""


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _looks_like_entry(url, cat):
    """Heuristic: an entry page (leaf content) vs an index page (just
    links). For most categories we record everything and let
    title-extraction sort it out. For categories with ENTRY_PATH_FRAGMENT
    (e.g. archetype) we record only URLs that contain the fragment."""
    p = urllib.parse.urlparse(url)
    frag = ENTRY_PATH_FRAGMENT.get(cat)
    if frag is None:
        return True
    if frag not in p.path:
        return False
    # Path should be DEEPER than the fragment (i.e. there's something
    # after /archetypes/, not just the index page).
    return not p.path.rstrip("/").endswith(frag.rstrip("/"))


def crawl(cat, session, rate, refresh):
    """BFS from seeds with per-category depth cap. Each seed is depth 0;
    its children are depth 1; etc. Recursion stops at RECURSE_DEPTH[cat].
    This prevents the crawler from chasing bad relative links inside
    individual entry pages."""
    seen = set()
    pages = set()
    depth_cap = RECURSE_DEPTH.get(cat, 0)
    todo = [(norm_url(s), 0) for s in SEEDS.get(cat, [])]
    miss_count = 0
    while todo:
        url, depth = todo.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            html = fetch(url, session, force=refresh, rate=rate)
        except Exception as e:
            miss_count += 1
            continue
        for link in page_links(html, url):
            if not in_scope(link, cat) or link in seen:
                continue
            if _looks_like_entry(link, cat):
                pages.add(link)
            if depth < depth_cap:
                todo.append((link, depth + 1))
    if miss_count:
        print(f"  ({miss_count} index-page fetch misses suppressed)",
              file=sys.stderr)
    return pages


def build_index(session, rate, refresh, only=None):
    out = {}
    cats = only or list(SEEDS.keys())
    for cat in cats:
        print(f"\n=== Crawling {cat} ===")
        urls = crawl(cat, session, rate, refresh)
        print(f"  found {len(urls)} candidate pages")
        ents = {}
        fetch_miss = 0
        for i, url in enumerate(sorted(urls), 1):
            try:
                html = fetch(url, session, force=refresh, rate=rate)
            except Exception:
                fetch_miss += 1
                continue
            t = page_title(html)
            if not t:
                continue
            s = slugify(t)
            if s and s not in ents:
                ents[s] = {"name": t, "url": url}
            if i % 100 == 0:
                print(f"  ...titled {i}/{len(urls)}")
        out[cat] = ents
        msg = f"  {cat}: {len(ents)} unique entries"
        if fetch_miss:
            msg += f" ({fetch_miss} fetch misses suppressed)"
        print(msg)
    return out


def html_to_md(html):
    soup = BeautifulSoup(html, "html.parser")
    for sel in ["nav", "footer", "header", "aside", "script", "style"]:
        for el in soup.select(sel):
            el.decompose()
    cont = soup.find("main") or soup.find("article") or soup.body or soup
    for tag in cont.find_all(string=re.compile(r"Section 15.*Copyright", re.I)):
        block = tag.find_parent(["p", "div", "section"])
        if block:
            for sib in list(block.find_all_next()):
                sib.decompose()
            block.decompose()
            break
    lines = []
    def text_of(el):
        return " ".join(el.get_text(separator=" ", strip=True).split())
    # Non-mutating markdown extractor. Walks the element tree and builds
    # a string with ** for bold and * for italic, without modifying the
    # soup. Mutating with replace_with() during cont.descendants iteration
    # corrupts the iterator and silently skips subsequent paragraphs
    # (verified on the duskwalker page: 19 <p> tags, only 2 emitted).
    def md_text(el):
        parts = []
        for child in el.children:
            if getattr(child, "name", None) is None:
                # NavigableString
                t = str(child)
                if t:
                    parts.append(t)
            else:
                n = child.name.lower()
                inner = md_text(child)
                if not inner.strip():
                    parts.append(inner)
                    continue
                if n in ("strong", "b"):
                    parts.append(f"**{inner.strip()}**")
                elif n in ("em", "i"):
                    parts.append(f"*{inner.strip()}*")
                elif n == "br":
                    parts.append("\n")
                else:
                    parts.append(inner)
        return " ".join("".join(parts).split())
    def heading(el, lvl):
        t = md_text(el)
        if t:
            lines.append("#" * lvl + " " + t)
            lines.append("")
    def para(el):
        t = md_text(el)
        if t:
            lines.append(t)
            lines.append("")
    def lst(ul, ordered=False):
        for i, li in enumerate(ul.find_all("li", recursive=False), 1):
            t = md_text(li)
            if t:
                lines.append(f"{i}. {t}" if ordered else f"- {t}")
        lines.append("")
    def table(tbl):
        rows = tbl.find_all("tr")
        if not rows:
            return
        head = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
        if not head:
            return
        lines.append("| " + " | ".join(head) + " |")
        lines.append("| " + " | ".join("---" for _ in head) + " |")
        for r in rows[1:]:
            cs = [c.get_text(" ", strip=True) for c in r.find_all(["th", "td"])]
            if cs:
                while len(cs) < len(head):
                    cs.append("")
                lines.append("| " + " | ".join(cs) + " |")
        lines.append("")
    seen_h1 = False
    for el in cont.descendants:
        if not getattr(el, "name", None):
            continue
        n = el.name.lower()
        if n == "h1":
            seen_h1 = True
            heading(el, 1)
        elif not seen_h1:
            continue
        elif n in ("h2", "h3", "h4"):
            heading(el, int(n[1]))
        elif n == "p":
            para(el)
        elif n == "ul":
            lst(el, False)
        elif n == "ol":
            lst(el, True)
        elif n == "table":
            table(el)
    md = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return md


def detect_kind(name):
    if name.startswith("race_"):
        return "race"
    if name.startswith("class_prestige_"):
        return "prestige"
    if name.startswith("class_archetype_") or name.startswith("archetype_"):
        return "archetype"
    if name.startswith("class_"):
        return "class"
    if name.startswith("feat_"):
        return "feat"
    if name.startswith("trait_"):
        return "trait"
    if name.startswith("spell_"):
        return "spell"
    return None


def aliases(name):
    b = slugify(name)
    a = {b, b.replace("_", "")}
    # Strip trailing parenthetical category tags from PF1e feat names —
    # "Greater Disarm (Combat)" / "Banishing Critical (Combat, Critical)"
    # / "(Archetype)" — d20pfsrd page titles usually omit them.
    import re as _re
    stripped = _re.sub(
        r"\s*\((?:combat|critical|archetype|story|teamwork|style|grit|"
        r"performance|item creation|metamagic|mythic|panache|achievement|"
        r"animal companion|monster|racial)[^)]*\)\s*$", "", name,
        flags=_re.IGNORECASE)
    if stripped != name:
        a.add(slugify(stripped))
    # Same for trailing role/class suffix on archetype names ("Rogue
    # Archetype", "Cleric Archetype" etc. — verbose names attached during
    # the Phase 2b bulk-mechanize that aren't in d20pfsrd titles).
    role_stripped = _re.sub(
        r"\s*\(?(?:alchemist|antipaladin|arcanist|barbarian|bard|bloodrager|"
        r"brawler|cavalier|cleric|druid|fighter|gunslinger|hunter|"
        r"inquisitor|investigator|kineticist|magus|medium|mesmerist|monk|"
        r"ninja|occultist|oracle|paladin|psychic|ranger|rogue|samurai|"
        r"shaman|shifter|skald|slayer|sorcerer|spiritualist|summoner|"
        r"swashbuckler|vigilante|warpriest|witch|wizard)\s*archetype\)?\s*$",
        "", name, flags=_re.IGNORECASE)
    if role_stripped != name and role_stripped.strip():
        a.add(slugify(role_stripped))
    # PF1e Unchained variants are titled "Barbarian (Unchained)" in our
    # data but indexed by d20pfsrd as "Unchained Barbarian" (slug
    # `unchained_barbarian`). Try the swapped form.
    m_unc = _re.match(r"(.+?)\s*\(unchained\)\s*$", name, _re.IGNORECASE)
    if m_unc:
        a.add(slugify(f"unchained {m_unc.group(1)}"))
    # Strip noisy "(Redirect)" suffix sometimes attached to instance
    # names after a rename.
    redir_stripped = _re.sub(r"\s*\(redirect\)\s*$", "", name, flags=_re.IGNORECASE)
    if redir_stripped != name:
        a.add(slugify(redir_stripped))
    # "Confusion, Lesser" / "Animate Dead, Lesser" — comma-inverted form
    # used in some spell instances. d20pfsrd titles these as "Lesser X".
    m_comma = _re.match(r"^(.+?),\s*(.+?)\s*$", name)
    if m_comma:
        a.add(slugify(f"{m_comma.group(2)} {m_comma.group(1)}"))
    # "Evil (Protection From)" — paren-inverted form. Move parenthetical
    # phrase to the front: "Protection From Evil".
    m_paren = _re.match(r"^(.+?)\s*\((.+?)\)\s*$", name)
    if m_paren:
        a.add(slugify(f"{m_paren.group(2)} {m_paren.group(1)}"))
    # Regular plural <-> singular
    if b.endswith("s") and not b.endswith("ss"):
        a.add(b[:-1])
    a.add(b + "s")
    # Irregular English plurals seen in d20pfsrd titles:
    # f/fe <-> ves (dwarf/dwarves, elf/elves, half-elf/half-elves,
    # wolf/wolves, knife/knives, ...). Apply on the LAST segment of a
    # multi-word slug so "half_elf" -> "half_elves" works.
    parts = b.split("_")
    last = parts[-1] if parts else b
    if last.endswith("f"):
        a.add("_".join(parts[:-1] + [last[:-1] + "ves"]))
    elif last.endswith("fe"):
        a.add("_".join(parts[:-1] + [last[:-2] + "ves"]))
    elif last.endswith("ves"):
        a.add("_".join(parts[:-1] + [last[:-3] + "f"]))
        a.add("_".join(parts[:-1] + [last[:-3] + "fe"]))
    if b.startswith("the_"):
        a.add(b[4:])
    return sorted(a)


def match(stats, cat, idx):
    name = stats.get("name", {})
    if isinstance(name, dict):
        name = name.get("value", "")
    if not name:
        return None, "no-name"
    al = aliases(name)
    for a in al:
        if a in idx:
            return idx[a]["url"], f"exact:{a}"
    for a in al:
        for slug, ent in idx.items():
            if slug.endswith("_" + a) or slug.startswith(a + "_"):
                return ent["url"], f"partial:{a}~{slug}"
    cands = difflib.get_close_matches(al[0], list(idx.keys()), n=1, cutoff=0.78)
    if cands:
        return idx[cands[0]]["url"], f"fuzzy:{cands[0]}"
    return None, "no-match"


def load_idx():
    if not INDEX_PATH.exists():
        print(f"missing {INDEX_PATH} -- run --build-index first", file=sys.stderr)
        sys.exit(2)
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def apply_rewrites(kind, write, session, rate, idx, limit=0):
    counts = defaultdict(int)
    unmatched, fetch_fails, short = [], [], []
    def relevant(n):
        k = detect_kind(n)
        return (k is not None) if kind == "all" else (k == kind)
    files = sorted(p for p in INST_DIR.iterdir()
                   if p.is_file() and p.name.endswith(".rpg.json")
                   and relevant(p.name))
    if limit:
        files = files[:limit]
    for p in files:
        k = detect_kind(p.name)
        if not k:
            continue
        cat_idx = idx.get(k, {})
        if not cat_idx:
            counts["no-index"] += 1
            continue
        try:
            raw = p.read_bytes().rstrip(b"\x00").rstrip().decode("utf-8")
            data = json.loads(raw)
        except Exception as e:
            counts["bad-json"] += 1
            unmatched.append((p.name, k, f"parse: {e}"))
            continue
        stats = data.get("stats", {})
        lb = stats.get("lore")
        if not isinstance(lb, dict):
            lb = {"value": ""}
            stats["lore"] = lb
        if SENTINEL in (lb.get("value") or ""):
            counts["already"] += 1
            continue
        url, strat = match(stats, k, cat_idx)
        if url is None:
            counts["unmatched"] += 1
            unmatched.append((p.name, k, "no URL match"))
            continue
        try:
            html = fetch(url, session, rate=rate)
        except Exception as e:
            counts["fetch-fail"] += 1
            fetch_fails.append((p.name, url, str(e)))
            continue
        md = html_to_md(html)
        min_prose_for_kind = MIN_PROSE_BY_KIND.get(k, MIN_PROSE)
        if len(md) < min_prose_for_kind:
            counts["too-short"] += 1
            short.append((p.name, url, len(md)))
            continue
        lb["value"] = SENTINEL + "\n" + md
        counts["rewrite"] += 1
        if write:
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    mode = "WRITTEN" if write else "DRY-RUN"
    print(f"\n=== [{mode}] kind={kind} files={len(files)} ===")
    for k, n in sorted(counts.items()):
        print(f"  {k}: {n}")
    if unmatched:
        print(f"\n--- {len(unmatched)} unmatched (NEEDS ACTION) ---")
        for fn, k, m in unmatched[:50]:
            print(f"  [{k}] {fn}: {m}")
        if len(unmatched) > 50:
            print(f"  ...{len(unmatched)-50} more")
        print(f"\nFix by adding entries to {INDEX_PATH} under category:")
        print('  "<slug>": {"name": "<title>", "url": "<full-url>"}')
    if fetch_fails:
        print(f"\n--- {len(fetch_fails)} fetch failures ---")
        for fn, url, e in fetch_fails[:20]:
            print(f"  {fn} <- {url}: {e}")
    if short:
        eff_min = MIN_PROSE_BY_KIND.get(kind, MIN_PROSE) if kind != "all" else MIN_PROSE
        print(f"\n--- {len(short)} pages too short (<{eff_min} chars) ---")
        for fn, url, n in short[:20]:
            print(f"  {fn} <- {url}: {n} chars")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--build-index", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--kind",
                    choices=["all", "race", "class", "prestige", "archetype",
                             "feat", "trait", "spell"], default="all")
    ap.add_argument("--only-categories", nargs="*")
    ap.add_argument("--refresh-index", action="store_true")
    ap.add_argument("--rate-limit-seconds", type=float, default=1.5)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if not (a.build_index or a.apply):
        ap.error("specify --build-index or --apply")
    session = requests.Session()
    if a.build_index:
        existing = {}
        if INDEX_PATH.exists():
            try:
                existing = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        idx = build_index(session, a.rate_limit_seconds, a.refresh_index,
                          a.only_categories)
        merged = dict(existing)
        merged.update(idx)
        INDEX_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False),
                              encoding="utf-8")
        print(f"\nIndex saved to {INDEX_PATH}")
        for k, v in merged.items():
            print(f"  {k}: {len(v)} entries")
        print(f"Total: {sum(len(v) for v in merged.values())} entries")
        return
    idx = load_idx()
    apply_rewrites(a.kind, a.write, session, a.rate_limit_seconds, idx, a.limit)


if __name__ == "__main__":
    main()
