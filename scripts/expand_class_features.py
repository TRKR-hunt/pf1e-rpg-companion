#!/usr/bin/env python3
"""B.1.5 Phase 2a-EXPAND. Parse each base class's folded `lore` SRD
class table, add any per-level feature missing from the curated
Phase-2a class_features. AUGMENT-ONLY + idempotent + assert-driven:
existing ids (Phase-2a + Phase-2b-referenced + prior runs) are never
overwritten or removed; a computed id colliding with an existing one
is skipped+logged. resource<class_feature>[] is inline (gotcha #16) so
zero new top-level instances.

Usage: python scripts/expand_class_features.py [--apply]
(no flag = dry run, prints per-class adds; --apply writes files)
"""
import json, glob, os, re, sys

RI = "pf1e/resource_instances"
APPLY = "--apply" in sys.argv

LVL = r'(\d+)(?:st|nd|rd|th)'
# a level row: "<N>th +<bab>[/+..] +<F> +<R> +<W> <Special...>"
ROW = re.compile(LVL + r'\s+\+\d[\d/+]*\s+\+\d+\s+\+\d+\s+\+\d+\s+(.*?)'
                 r'(?=' + LVL + r'\s+\+\d|$)', re.S)
# The per-day spell grid always begins with a STANDALONE 1-2 digit
# count (" 3 ", " 4 ", "1+1") then dash glyphs. Cut Special there.
# Scaling like "+1", "1/day", "1d6" is NOT standalone (preceded by
# '+' / followed by '/' or 'd') so it survives.
SPELLCUT = re.compile(r'\s\d{1,2}(?:\+\d)?(?=\s|$)')

def slug(s):
    s = re.sub(r'\(.*?\)', ' ', s)               # drop "(Ex)/(or ...*)"
    s = re.sub(r'\+\s*\d+\S*', ' ', s)           # drop "+1", "+1d6"
    s = re.sub(r'\b\d+\s*/\s*day\b', ' ', s, flags=re.I)
    s = re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')
    return re.sub(r'_+', '_', s)[:46]

def clean_name(s):
    s = re.sub(r'\(or\b.*', '', s)
    s = re.sub(r'\s+', ' ', s).strip(" ,.;*")
    return s[:80]

# A real per-level feature cell is a short noun phrase. Prose that
# leaks past the last (L20) row is a sentence — reject it. No bad data.
_PROSE = re.compile(r'\b(gains?|learns?|reduces?|adds?|becomes?|can|cannot|'
                    r'chooses?|must|may|treats?|uses?|takes?|deals?|makes?|'
                    r'is|are|has|have|the following)\b', re.I)
_STOP = re.compile(r'^(a|an|the|he|she|it|this|at|in|on|as|to|for|with|'
                   r'while|when|if|each|whenever|any|all|see)\b', re.I)
def is_feature_name(nm):
    w = nm.split()
    if not (1 <= len(w) <= 6):
        return False
    if _STOP.match(nm) or _PROSE.search(nm):
        return False
    return True

def parse_table(lore):
    i = lore.find("Table")
    if i < 0:
        return []
    body = lore[i:i + 6000]
    out = []
    for m in ROW.finditer(body):
        lvl = int(m.group(1))
        special = m.group(2)
        # Last (L20) row has no trailing level marker, so it can run
        # into the post-table prose. Table cells never contain '.' —
        # cut at the first sentence period; then the spell-grid cut.
        dot = special.find(". ")
        if dot >= 0:
            special = special[:dot]
        g = SPELLCUT.search(special)
        if g:
            special = special[:g.start()]
        special = special.strip()
        if not special or lvl < 1 or lvl > 20:
            continue
        for part in special.split(","):
            nm = clean_name(part)
            if len(nm) < 3 or nm.lower() in ("â", "—", "spells", "special"):
                continue
            if not is_feature_name(nm):
                continue
            out.append((lvl, nm))
    return out

base = []
for f in glob.glob(os.path.join(RI, "class_*__crb_.rpg.json")):
    d = json.load(open(f, encoding="utf-8"))
    if d.get("resource_id") != "class":
        continue
    s = d["stats"]
    if (s.get("is_prestige", {}) or {}).get("value"):
        continue
    base.append((f, d, s))

tot_before = tot_after = added = skipped = 0
report = []
for f, d, s in base:
    cid = s["id"]
    slug_base = re.sub(r'__crb_$', '', cid)
    cf = s.get("class_features", {}).get("value", [])
    existing = {e["stats"]["id"] for e in cf}
    tot_before += len(cf)
    lore = (s.get("lore", {}) or {}).get("value", "") or ""
    parsed = parse_table(lore)
    seen = set()
    newf = []
    for lvl, nm in parsed:
        fid = slug_base + "_" + slug(nm)
        if not slug(nm) or fid in existing or fid in seen:
            if fid in existing:
                skipped += 1
            continue
        seen.add(fid)
        newf.append({"resource_id": "class_feature", "stats": {
            "id": fid, "name": {"value": nm}, "level": {"value": lvl},
            "description": {"value": "L%d: %s" % (lvl, nm)},
            "feature_category": {"value": "base"}}})
    if newf:
        s["class_features"]["value"] = cf + newf
        added += len(newf)
        if APPLY:
            json.dump(d, open(f, "w", encoding="utf-8", newline="\n"),
                      indent=2, ensure_ascii=False)
    tot_after += len(cf) + len(newf)
    report.append((cid, len(cf), len(cf) + len(newf), len(newf),
                   "EMPTY-LORE" if not lore else ""))

report.sort(key=lambda r: r[3], reverse=True)
print("MODE:", "APPLY" if APPLY else "DRY-RUN")
print("base classes:", len(base), "| features before:", tot_before,
      "| after:", tot_after, "| added:", added, "| id-collisions skipped:", skipped)
print("top growth:")
for r in report[:12]:
    print("  %-26s %3d -> %3d  (+%d) %s" % r)
print("zero-growth:", [r[0] for r in report if r[3] == 0])
