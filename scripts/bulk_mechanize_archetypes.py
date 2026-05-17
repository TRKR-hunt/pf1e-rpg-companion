#!/usr/bin/env python3
"""B.1.5 Phase 2b-BULK. Mechanize scraped archetype_* lore into
class_archetype instances. Idempotent, augment-only, assert-driven:
- parent = the base class whose Phase-2a-EXPAND feature ids the
  archetype's parsed "This replaces X" phrases actually match (this
  auto-disambiguates parent; a wrong guess yields 0 matches -> skip).
- replaces[] only ever contains REAL feature ids; unmatched phrases
  logged & dropped; 0 matched -> archetype skipped (no bad data).
- target id arch_<slug>__crb_; if it already exists (Phase-2b's 20 or
  a prior run) the archetype is skipped (preserve / idempotent).
- lore-fold: scraped prose -> archetype.lore; source instance deleted.
Usage: python scripts/bulk_mechanize_archetypes.py [--apply]
"""
import json, glob, os, re, sys, collections

RI = "pf1e/resource_instances"
APPLY = "--apply" in sys.argv

STOP = {"the","a","an","and","or","of","to","at","gained","level","levels",
        "ability","class","feature","features","this","st","nd","rd","th",
        "his","her","its","s"}
def norm(s):
    s = s.lower()
    s = re.sub(r"[’']s\b", "", s)
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bgained at .*?level[s]?\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t and t not in STOP]
    # crude singularise
    toks = [re.sub(r"ies$", "y", t) for t in toks]
    toks = [t[:-1] if t.endswith("s") and len(t) > 3 else t for t in toks]
    return toks

# base (non-prestige) classes -> id, name, [(fid, set(name_tokens))]
classes = []
for f in glob.glob(os.path.join(RI, "class_*__crb_.rpg.json")):
    d = json.load(open(f, encoding="utf-8"))
    if d.get("resource_id") != "class":
        continue
    s = d["stats"]
    if (s.get("is_prestige", {}) or {}).get("value"):
        continue
    feats = []
    for e in s.get("class_features", {}).get("value", []):
        st = e["stats"]
        nm = (st.get("name", {}) or {}).get("value", "")
        feats.append((st["id"], set(norm(nm)), st.get("level", {}).get("value", 1)))
    classes.append((s["id"], (s.get("name", {}) or {}).get("value", ""),
                    s["id"].replace("__crb_", ""), feats))

existing_arch = {json.load(open(f, encoding="utf-8"))["stats"]["id"]
                 for f in glob.glob(os.path.join(RI, "class_archetype_*__crb_.rpg.json"))}

RE_SWAP = re.compile(
    r"(?:this(?:\s+\w+){0,3}\s+(?:replaces|alters and replaces)|"
    r"\breplaces)\s+(?:the\s+)?([a-z][a-z0-9’' ,/\-]{2,140}?)"
    r"(?=\s+(?:gained|ability|feature|class\b)|[.;]|\s+at \d)", re.I)
RE_ADDHDR = re.compile(r"([A-Z][A-Za-z][A-Za-z '\-]{2,40})\s*\((?:Ex|Su|Sp|Ex/Su)\)")
# generic tokens that must NOT be the *only* thing a phrase/feature share
GENERIC = {"spell","feat","bonus","ability","power","class","level",
           "improved","greater","lesser","minor","major","extra"}

def subphrases(raw):
    """A captured swap clause may enumerate several features:
    'wild empathy, woodland stride, and trackless step'. Split it so
    each feature is matched independently (raises true-parent score)."""
    raw = re.sub(r"\b\d+(?:st|nd|rd|th)?\b", " ", raw)
    parts = re.split(r"\s*,\s*|\s+and\s+|\s*&\s*|\s*/\s*", raw)
    return [set(norm(p)) for p in parts if norm(p)]

def slug(s):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")[:54]

shipped = 0
skips = collections.Counter()
skip_samples = collections.defaultdict(list)
ship_log = []
post_expand = []   # archetypes that matched a feature id added by EXPAND

# id->is_expand map per class for "only-because-EXPAND" attribution
EXPAND_TAIL = {}   # cid -> set of feature ids beyond the first curated block
for cid, cname, cslug, feats in classes:
    EXPAND_TAIL[cid] = set()

for f in sorted(glob.glob(os.path.join(RI, "archetype_*.rpg.json"))):
    d = json.load(open(f, encoding="utf-8"))
    s = d["stats"]
    aname = (s.get("name", {}) or {}).get("value", "")
    src = (s.get("source", {}) or {}).get("value", "") or "crb"
    prose = (s.get("description", {}) or {}).get("value", "") or ""
    aid = "arch_" + slug(aname) + "__crb_"
    if aid in existing_arch:
        skips["already_mechanized_or_phase2b"] += 1
        continue

    raw_clauses = [m.group(1).strip() for m in RE_SWAP.finditer(prose)]
    pset = []
    for rc in raw_clauses:
        pset.extend(subphrases(rc))
    pset = [p for p in pset if p]
    if not pset:
        skips["no_parseable_swaps"] += 1
        if len(skip_samples["no_parseable_swaps"]) < 10:
            skip_samples["no_parseable_swaps"].append(aname)
        continue

    def feat_match(ph, fnt):
        if not fnt:
            return False
        if not (ph == fnt or ph <= fnt or fnt <= ph):
            return False
        # the overlap must include >=1 non-generic token, else a phrase
        # sharing only "spell"/"feat"/"bonus" would match unrelated feats
        return bool((ph & fnt) - GENERIC)

    # score every base class by how many distinct phrases match a feature
    scored = []
    for cid, cname, cslug, feats in classes:
        matched_ids = []
        for ph in pset:
            for fid, fnt, lvl in feats:
                if feat_match(ph, fnt):
                    matched_ids.append(fid)
                    break
        mi = list(dict.fromkeys(matched_ids))
        title_bonus = 1 if re.search(r"(?<![a-z])" + re.escape(cname.lower())
                                     + r"(?![a-z])", aname.lower()) else 0
        scored.append((len(mi), title_bonus, cid, cname, mi))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top = scored[0]
    nmatch, top_tb, pcid, pcname, repl = top
    # Unchained twins (Barbarian / Barbarian (Unchained), Rogue/…,
    # Monk/…) share nearly all features so they always tie — that is
    # NOT genuine parent ambiguity. Treat them as one family; pick the
    # variant the title names, else the non-Unchained canonical one.
    def fam(n):
        return re.sub(r"\s*\(unchained\)", "", n, flags=re.I).strip().lower()
    same_fam = [s for s in scored if s[0] == nmatch and fam(s[3]) == fam(pcname)]
    if len(same_fam) > 1:
        named = [s for s in same_fam if s[1]]
        base_v = [s for s in same_fam if "unchained" not in s[3].lower()]
        pick = (named or base_v or same_fam)[0]
        nmatch, top_tb, pcid, pcname, repl = pick
    if nmatch < 1:
        skips["no_swaps_matched_any_class"] += 1
        if len(skip_samples["no_swaps_matched_any_class"]) < 10:
            skip_samples["no_swaps_matched_any_class"].append(
                aname + " | " + "; ".join(" ".join(p) for p in pset[:3]))
        continue
    # parent-margin: the winner must clearly out-match the runner-up,
    # otherwise the parent is ambiguous (Category C, out of scope).
    rivals = [s for s in scored[1:] if s[0] >= 1 and fam(s[3]) != fam(pcname)]
    runner = rivals[0][0] if rivals else 0
    if nmatch <= runner and not top_tb:
        skips["parent_ambiguous_margin"] += 1
        if len(skip_samples["parent_ambiguous_margin"]) < 10:
            skip_samples["parent_ambiguous_margin"].append(
                "%s | %s(%d) vs %s(%d)" % (aname, pcname, nmatch,
                                           rivals[0][3], runner))
        continue

    # adds[]: nearest "<Name> (Ex/Su/Sp)" header preceding a replace clause
    adds = []
    for m in re.finditer(r"(?:this(?:\s+\w+){0,3}\s+replaces|\breplaces)\s", prose, re.I):
        pre = prose[max(0, m.start() - 400):m.start()]
        hs = list(RE_ADDHDR.finditer(pre))
        if hs:
            h = hs[-1]
            nm = h.group(1).strip()
            desc = pre[h.end():].strip()[:220]
            fid = slug(pcid.replace("__crb_", "")) + "_arch_" + slug(nm)
            if not any(x["stats"]["id"] == fid for x in adds):
                adds.append({"resource_id": "class_feature", "stats": {
                    "id": fid[:60], "name": {"value": nm[:80]},
                    "level": {"value": 1},
                    "description": {"value": (nm + " — " + desc)[:300]},
                    "feature_category": {"value": "archetype"}}})
    adds = adds[:8]

    inst = {"resource_id": "class_archetype", "stats": {
        "id": aid, "name": {"value": aname}, "source": {"value": "crb"},
        "parent_class_id": {"value": pcid},
        "parent_class_name": {"value": pcname},
        "replaces": {"value": repl},
        "adds": {"value": adds},
        "prerequisites": {"value": []},
        "is_lore_only": {"value": False},
        "lore": {"value": prose}}}
    if APPLY:
        json.dump(inst, open(os.path.join(RI, "class_archetype_%s__crb_.rpg.json"
                  % slug(aname)), "w", encoding="utf-8", newline="\n"),
                  indent=2, ensure_ascii=False)
        os.remove(f)
    existing_arch.add(aid)
    shipped += 1
    ship_log.append((aname, pcname, len(repl), len(adds)))

print("MODE:", "APPLY" if APPLY else "DRY-RUN")
print("shipped:", shipped, "| skipped total:", sum(skips.values()))
for k, v in skips.most_common():
    print("  skip[%s] = %d" % (k, v))
print("sample skips:")
for k, ss in skip_samples.items():
    print(" ", k, "->", ss[:6])
print("sample shipped:", ship_log[:12])
