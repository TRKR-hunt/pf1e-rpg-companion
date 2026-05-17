#!/usr/bin/env python3
"""B.1.5 Phase 2h. Clean scraped lore prose: fix mojibake, strip the
TOC/breadcrumb soup at the head, inject paragraph breaks at known
section headings, flag mid-sentence truncation.

Idempotent (re-run on a cleaned string => 0 changes), augment-only
(only the lore/description text field is touched), assert-driven
(only documented patterns are altered; if a string has none it is
left byte-identical and counted as "nochange").

Targets:
  class_*__crb_           resource_id=class            stats.lore
  class_archetype_*__crb_ resource_id=class_archetype  stats.lore
  race_*__crb_            resource_id=race             stats.lore
  archetype_*__crb_       resource_id=archetype        stats.description
Usage: python scripts/fix_lore_formatting.py [--apply]
"""
import json, glob, os, re, sys, collections

RI = "pf1e/resource_instances"
APPLY = "--apply" in sys.argv

# (A) mojibake: exact double-encoded (UTF-8 bytes read as Latin-1)
# codepoint runs -> correct char. Keys are explicit \x escapes so
# each is the precise sequence; a clean string contains none (no-op).
# Order: 3-byte then 2-byte then lone stray (order-critical).
MOJIBAKE = [
    ("\xe2\x80\x99", "’"),  # right single quote / apostrophe
    ("\xe2\x80\x98", "‘"),  # left single quote
    ("\xe2\x80\x9c", "“"),  # left double quote
    ("\xe2\x80\x9d", "”"),  # right double quote
    ("\xe2\x80\x94", "—"),  # em dash
    ("\xe2\x80\x93", "–"),  # en dash
    ("\xe2\x80\xa6", "…"),  # ellipsis
    ("\xe2\x80\xa2", "•"),  # bullet
    ("\xe2\x84\xa2", "™"),  # tm
    ("\xe2\x82\xac", "€"),  # euro
    ("\xc3\x97", "×"),       # multiplication sign
    ("\xc3\xa9", "é"),       # e-acute
    ("\xc3\xa8", "è"),       # e-grave
    ("\xc3\xb1", "ñ"),       # n-tilde
    ("\xc3\xa1", "á"),       # a-acute
    ("\xc2\xb0", "°"),       # degree
    ("\xc2\xbd", "½"),       # one-half
    ("\xc2\xbc", "¼"),       # one-quarter
    ("\xc2\xa0", " "),             # nbsp -> space
    ("\xc2", ""),                  # stray lone (LAST - order-critical)
    # U+FFFD-prefixed variants: the lead byte was lost to the unicode
    # replacement char during scrape but the trailing 2 survive.
    ("�\x80\x99", "’"), ("�\x80\x98", "‘"),
    ("�\x80\x9c", "“"), ("�\x80\x9d", "”"),
    ("�\x80\x94", "—"), ("�\x80\x93", "–"),
    ("�\x80\xa6", "…"), ("�\x80\xa2", "•"),
]

SLUGRE = re.compile(r"^##\s*[a-z0-9_ '\-]+\s*\n\n", re.I)
BREADCRUMB = re.compile(r"^\s*Home\s*>.*?\bContents\b\s*", re.S)
IMGPERM = re.compile(r"Image used by permission[^.]*\.\s*", re.I)
# prose starts at a capitalised word then >=4 consecutive lowercase
# words. TOC entries are Title-Case so they never satisfy this.
PROSE = re.compile(r"[A-Z][A-Za-z'’\-]+(?:\s+[a-z][a-z'’\-]+){4,}")

HEADINGS = ["Weapon and Armor Proficiency", "Class Features",
            "Class Skills", "Spellcasting", "Bonus Spells",
            "Bonus Feats", "Bonus Languages", "Standard Racial Traits",
            "Alternate Racial Traits", "Final Revelation",
            "Capstone Ability", "Requirements"]

def fix_mojibake(t):
    for bad, good in MOJIBAKE:
        if bad in t:
            t = t.replace(bad, good)
    return t

def strip_head(t):
    t2 = SLUGRE.sub("", t)
    t2 = BREADCRUMB.sub("", t2)
    t2 = IMGPERM.sub("", t2)
    if t2 != t:                        # had a slug/breadcrumb head
        m = PROSE.search(t2[:4000])    # cut the Title-Case TOC run
        if m and m.start() > 0:
            t2 = t2[m.start():]
        return t2.lstrip()
    return t

def inject_headings(t):
    # ONLY at a true sentence boundary: a period+space (or ?/!/quote)
    # immediately before the heading word. This makes "Diminished
    # Spellcasting" (mid-phrase, no preceding ". ") safe, and is
    # idempotent (after pass 1 the heading is "\n\n## H\n", preceded
    # by "\n" not ". ", so it never re-matches).
    for h in HEADINGS:
        t = re.sub(r'(?<=[.!?”"])\s+' + re.escape(h) + r'\b:?[ ]?',
                   "\n\n## " + h + "\n\n", t)
    return re.sub(r"\n{3,}", "\n\n", t)

def clean(t):
    if not t or not t.strip():
        return t, "empty"
    orig = t
    t = fix_mojibake(t)
    t = strip_head(t)
    t = inject_headings(t)
    if len(orig) in (8000, 8010) and not re.search(r'[.!?”"]\s*$', t):
        if "truncated; see source" not in t:
            t = t.rstrip() + " [...truncated; see source]"
    t = t.strip()
    return (orig, "nochange") if t == orig else (t, "cleaned")

FIELD = {"class": "lore", "class_archetype": "lore",
         "race": "lore", "archetype": "description"}

stats = collections.Counter()
moj_before = moj_after = 0
samples = []
for f in sorted(glob.glob(os.path.join(RI, "*.rpg.json"))):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    rid = d.get("resource_id")
    fld = FIELD.get(rid)
    if not fld:
        continue
    node = d.get("stats", {}).get(fld)
    if not isinstance(node, dict) or "value" not in node:
        stats[rid + ":no_field"] += 1
        continue
    val = node.get("value") or ""
    if not isinstance(val, str):
        continue
    for bad, _ in MOJIBAKE:
        moj_before += val.count(bad)
    new, status = clean(val)
    stats[rid + ":" + status] += 1
    for bad, _ in MOJIBAKE:
        moj_after += new.count(bad)
    if status == "cleaned":
        if len(samples) < 5:
            samples.append((os.path.basename(f), val[:150], new[:200]))
        if APPLY:
            node["value"] = new
            json.dump(d, open(f, "w", encoding="utf-8", newline="\n"),
                      indent=2, ensure_ascii=False)

print("MODE:", "APPLY" if APPLY else "DRY-RUN")
for k in sorted(stats):
    print("  %-34s %d" % (k, stats[k]))
print("mojibake sequences  before=%d  after=%d" % (moj_before, moj_after))
print("--- 5 before/after samples ---")
for fn, b, a in samples:
    print("\n#", fn)
    print("  BEFORE:", repr(b))
    print("  AFTER :", repr(a))
