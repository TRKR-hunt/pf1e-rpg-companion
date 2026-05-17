#!/usr/bin/env python3
"""DIAGNOSTIC ONLY (archetype blocker analysis). Read-only: classifies
every unmechanized archetype_* lore instance by why it can't be turned
into a mechanical class_archetype. Writes no resources."""
import json, glob, os, re, collections, hashlib

RI = "pf1e/resource_instances"

# base (non-prestige) mechanical classes: name -> (id, set(feature-name-slugs), set(feature ids))
base = {}
for f in glob.glob(os.path.join(RI, "class_*__crb_.rpg.json")):
    d = json.load(open(f, encoding="utf-8"))
    if d.get("resource_id") != "class":
        continue
    s = d["stats"]
    if (s.get("is_prestige", {}) or {}).get("value"):
        continue
    nm = (s.get("name", {}) or {}).get("value", "").lower().strip()
    fids = [e["stats"]["id"] for e in s.get("class_features", {}).get("value", [])]
    fnames = set()
    for e in s.get("class_features", {}).get("value", []):
        n = (e["stats"].get("name", {}) or {}).get("value", "").lower()
        fnames.add(re.sub(r'[^a-z0-9]+', ' ', n).strip())
    base[nm] = (s["id"], fnames, set(fids))

CANON_SRC = {"crb","apg","um","uc","acg","ultimate_combat","ultimate_magic",
  "advanced_players_guide","advanced_class_guide","occult_adventures",
  "ultimate_intrigue","ultimate_wilderness","pathfinder_unchained",
  "pathfinder_roleplaying_game_adventurers_guide","martial_arts_handbook",
  "monster_hunter_s_handbook","isg","the_inner_sea_world_guide",
  "paths_of_prestige","paths_of_the_righteous","chronicle_of_legends",
  "pathfinder_rpg_core_rulebook","pathfinder_roleplaying_game_acg",
  "book_of_the_damned","unknown"}
TPP_HINT = re.compile(r'legendary|kobold|dreamscarred|rogue_genius|3pp|rite_publishing|'
                      r'super_genius|drop_dead|purple_duck', re.I)

RE_REPL = re.compile(r'\b(replaces?|in place of|instead of|alters?|modifies|'
                     r'this (?:ability |archetype )?replaces)\b', re.I)
RE_LVL = re.compile(r'\bat \d+(?:st|nd|rd|th) level\b', re.I)

rows = []
for f in sorted(glob.glob(os.path.join(RI, "archetype_*.rpg.json"))):
    s = json.load(open(f, encoding="utf-8"))["stats"]
    name = (s.get("name", {}) or {}).get("value", "")
    src = (s.get("source", {}) or {}).get("value", "")
    prose = (s.get("description", {}) or {}).get("value", "") or ""
    lname = name.lower()
    plow = prose.lower()

    # parent detection: base-class names appearing in name or prose
    hits = []
    for cn in base:
        # word-ish boundary; require >=4 char class names to avoid noise
        if len(cn) < 4:
            continue
        if re.search(r'(?<![a-z])' + re.escape(cn) + r'(?![a-z])', lname) or \
           re.search(r'(?<![a-z])' + re.escape(cn) + r'(?![a-z])', plow):
            hits.append(cn)
    hits = sorted(set(hits))
    if len(hits) == 1:
        parent_state, parent = "yes", hits[0]
    elif len(hits) > 1:
        # prefer one whose name is in the archetype name
        innm = [h for h in hits if h in lname]
        if len(innm) == 1:
            parent_state, parent = "yes", innm[0]
        else:
            parent_state, parent = "ambiguous", "|".join(hits[:4])
    else:
        parent_state, parent = "no", ""

    # TIGHT signal: the exact d20pfsrd swap sentence
    # "This [ability/archetype] replaces [the] <feature>[ gained at Nth level]."
    swap_phrases = [m.group(1).strip().lower() for m in re.finditer(
        r'(?:this(?:\s+\w+){0,2}\s+replaces|^replaces|\breplaces)\s+'
        r'(?:the\s+)?([a-z][a-z\' \-/]{2,40}?)'
        r'(?:\s+(?:ability|feature|gained|at|and|class)\b|[.,;])',
        prose, re.I | re.M)]
    swap_phrases = [p for p in swap_phrases if len(p) > 2]
    nrepl = len(swap_phrases)
    repl_parse = "yes" if nrepl >= 1 else "no"

    # do the swap phrases line up with this parent's Phase-2a feature names?
    matched = 0
    if parent_state == "yes" and parent in base:
        _, fnames, _ = base[parent]
        fjoin = " | ".join(fnames)
        for ph in swap_phrases:
            toks = [t for t in re.sub(r'[^a-z0-9 ]', ' ', ph).split() if len(t) > 3]
            if toks and any(t in fjoin for t in toks):
                matched += 1

    # Evidence: ALL 99 archetype sources are 1st-party Paizo (TPP_HINT
    # matches 0). E is therefore only genuine 3PP (none) OR an
    # archetype whose identified parent is not one of our 46
    # mechanical classes — NOT "source string unrecognised".
    is_tpp = bool(TPP_HINT.search(src))
    parent_known = parent_state == "yes" and parent in base

    # categorize
    if is_tpp or (parent_state == "yes" and parent not in base):
        cat = "E"
    elif parent_known and nrepl >= 1 and matched >= 1:
        cat = "A"   # parent known + extractable swaps + >=1 lines up w/ Phase-2a
    elif parent_known and nrepl >= 1:
        cat = "B"   # extractable swaps but feature names don't match Phase-2a ids
    elif (parent_state in ("yes", "ambiguous")) and (nrepl >= 1 or parent_state == "ambiguous"):
        cat = "C"   # ambiguous parent, or swaps w/ unknown parent — human review
    else:
        cat = "D"   # no parent AND no parseable swaps

    rows.append(dict(name=name, src=src, plen=len(prose), parent_state=parent_state,
                      parent=parent, repl=repl_parse, matched=matched, cat=cat,
                      sample=prose[:160].replace("\n", " ")))

cnt = collections.Counter(r["cat"] for r in rows)
out = []
W = out.append
W("# Archetype blocker analysis (DIAGNOSTIC — no resources written)\n")
W("## Total inventory + breakdown\n")
W("Total unmechanized archetype lore instances: **%d**\n" % len(rows))
for c in "ABCDE":
    W("- Category %s: **%d** (%.1f%%)" % (c, cnt.get(c, 0), 100.0*cnt.get(c,0)/len(rows)))
W("")
desc = {"A":"Fully mechanizable","B":"Partial (subset replaces)",
        "C":"Disambiguation/human review","D":"Intractable (data insufficient)",
        "E":"3PP / class not mechanized / out-of-scope"}
for c in "ABCDE":
    sub = [r for r in rows if r["cat"] == c]
    W("## Category %s — %s — %d\n" % (c, desc[c], len(sub)))
    for r in sub[:10]:
        W("- **%s** (src `%s`, parent=%s/%s, repl=%s, matched=%d) — %s" %
          (r["name"], r["src"], r["parent_state"], r["parent"] or "-",
           r["repl"], r["matched"], r["sample"][:90]))
    W("")
    if c == "B" and sub:
        avg = sum(r["matched"] for r in sub)/len(sub)
        W("Category B avg matched-feature-names per archetype: %.2f\n" % avg)
    if c == "E":
        es = collections.Counter(r["src"] for r in sub)
        W("Category E source distribution (top 15): %s\n" %
          ", ".join("%s=%d" % kv for kv in es.most_common(15)))

mech = cnt.get("A",0) + cnt.get("B",0)
W("## Bottom-line\n")
W("Practically mechanizable now (A+B): **%d** (%.1f%%). "
  "Needs human review (C): %d. Genuine wall (D): %d. Out-of-scope (E): %d.\n"
  % (mech, 100.0*mech/len(rows), cnt.get("C",0), cnt.get("D",0), cnt.get("E",0)))

open(".local-notes/SESSION_REPORT_ARCHETYPE_BLOCKER_ANALYSIS.md", "w",
     encoding="utf-8", newline="\n").write("\n".join(out))
print("rows:", len(rows), "| per cat:", dict(cnt))
print("base classes used as parents:", len(base))
