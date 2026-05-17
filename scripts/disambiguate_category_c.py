#!/usr/bin/env python3
"""B.1.5 Phase 2c. Disambiguate the Category-C archetypes the bulk
session deferred (cross-class match ties + stem-mismatches).

The bulk generator deferred these because >=2 classes matched the
parsed swaps equally — raw match-count alone could not pick a parent.
This pass adds *prose evidence* signals, in order of trust:

  1. lore class-name mentions — the SRD writes swaps as "This ability
     replaces the slayer's weapon and armor proficiencies" / "her
     slayer level", so among the TIED candidates the true parent's
     name dominates the prose. (possessive + plural counted)
  2. class-defining keyword (grit->gunslinger, panache->swashbuckler,
     arcane reservoir->arcanist, studied target->slayer, bloodline->
     bloodrager, ki pool->monk, raging song->skald, …) +2 each.
  3. title-as-evidence — in a TIED context only, a candidate whose
     base name appears in the archetype title gets +3 (bulk treats
     title as unreliable; here it is a permitted tie-breaker).

Margin-restored: ship only if the winning candidate's evidence score
is > 0 AND beats the runner-up by >= MARGIN; else stay deferred
(true human-review Category-C remainder — never guessed).

Stem-mismatch cases: parent chosen by the SAME prose/title evidence
over ALL classes (match-count gave nothing), then swaps re-matched
against that parent's real features with a minimal STEM map
(documented; only general plural/'s' artefacts, not per-archetype).

Assert-driven & augment-only & idempotent, exactly as bulk:
- replaces[] only ever real Phase-2a-EXPAND ids on the CHOSEN parent
- adds[] must be non-empty (a real mechanical change) else skip
- target id arch_<slug>__crb_ already existing -> skip (preserve the
  841 shipped) ; source lore deleted on ship so a re-run can't dup.
Usage: python scripts/disambiguate_category_c.py [--apply]
"""
import json, glob, os, re, sys, collections

RI = "pf1e/resource_instances"
APPLY = "--apply" in sys.argv

# reuse the bulk parser primitives verbatim (single source of truth)
_bulk = open(os.path.join(os.path.dirname(__file__),
              "bulk_mechanize_archetypes.py")).read()
exec(_bulk.split("shipped = 0")[0])  # noqa: classes, RE_SWAP, subphrases,
# norm, slug, GENERIC, RE_ADDHDR, existing_arch, feat_match-equivalent

def fam(n):
    return re.sub(r"\s*\(unchained\)", "", n, flags=re.I).strip().lower()

def fmatch(ph, fnt):
    if not fnt:
        return False
    if not (ph == fnt or ph <= fnt or fnt <= ph):
        return False
    return bool((ph & fnt) - GENERIC)

# (2) class-defining keyword -> canonical base class name
KW = {"grit": "gunslinger", "panache": "swashbuckler",
      "arcane reservoir": "arcanist", "studied target": "slayer",
      "bloodline": "bloodrager", "ki pool": "monk",
      "raging song": "skald", "bardic performance": "bard",
      "eidolon": "summoner", "stern gaze": "inquisitor",
      "judgment": "inquisitor", "wild shape": "druid",
      "phrenic pool": "psychic", "arcane pool": "magus"}
# minimal, GENERAL stem normalisation for the stem-mismatch bucket
# (NOT per-archetype synonyms): plural/possessive artefacts only.
STEM = {"hexe": "hex", "arcane": "arcanist", "loremaster": "lore"}
MARGIN = 2

def base(cn):
    return re.sub(r"\s*\(unchained\)", "", cn, flags=re.I).strip().lower()

def name_score(prose_l, cn):
    b = base(cn)
    hits = len(re.findall(r"(?<![a-z])" + re.escape(b) + r"(?:'?s)?(?![a-z])",
                          prose_l))
    kw = sum(2 for k, v in KW.items() if v == b and k in prose_l)
    return hits + kw

def stem_tokens(tokset):
    return {STEM.get(t, t) for t in tokset}

shipped = 0
skips = collections.Counter()
ship_log = []
defer_rows = []

for f in sorted(glob.glob(os.path.join(RI, "archetype_*.rpg.json"))):
    s = json.load(open(f, encoding="utf-8"))["stats"]
    aname = (s.get("name", {}) or {}).get("value", "")
    prose = (s.get("description", {}) or {}).get("value", "") or ""
    pl = prose.lower()
    aid = "arch_" + slug(aname) + "__crb_"
    if aid in existing_arch:
        skips["already_shipped"] += 1
        continue

    raw = [m.group(1).strip() for m in RE_SWAP.finditer(prose)]
    pset = []
    for rc in raw:
        pset.extend(subphrases(rc))
    pset = [p for p in pset if p]
    if not pset:
        skips["catD_no_parseable_swap"] += 1
        defer_rows.append((aname, "no_parseable_swap"))
        continue

    # bulk's class scoring (to recover the same tie / stem state)
    scored = []
    for cid, cn, cslug, feats in classes:
        mi = []
        for ph in pset:
            for fid, fnt, lvl in feats:
                if fmatch(ph, fnt):
                    mi.append(fid)
                    break
        mi = list(dict.fromkeys(mi))
        tb = 1 if re.search(r"(?<![a-z])" + re.escape(cn.lower())
                            + r"(?![a-z])", aname.lower()) else 0
        scored.append([len(mi), tb, cid, cn, mi])
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    nm0 = scored[0][0]

    if nm0 < 1:
        bucket = "stem"
    else:
        topfam = fam(scored[0][3])
        riv = [x for x in scored[1:] if x[0] >= 1 and fam(x[3]) != topfam]
        sf = [x for x in scored if x[0] == nm0 and fam(x[3]) == topfam]
        nm, tb = scored[0][0], scored[0][1]
        if len(sf) > 1:
            nmd = [x for x in sf if x[1]]
            bv = [x for x in sf if "unchained" not in x[3].lower()]
            tb = (nmd or bv or sf)[0][1]
        if riv and nm <= riv[0][0] and not tb:
            bucket = "tie"
        else:
            skips["bulk_would_ship_unexpected"] += 1
            continue

    if bucket == "tie":
        topscore = scored[0][0]
        cands, seen = [], set()
        for x in scored:
            if x[0] != topscore:
                break
            if fam(x[3]) in seen:
                continue
            seen.add(fam(x[3]))
            cands.append(x)
        board = []
        for x in cands:
            sc = name_score(pl, x[3])
            if re.search(r"(?<![a-z])" + re.escape(base(x[3])) + r"(?![a-z])",
                         aname.lower()):
                sc += 3
            board.append((sc, x))
        board.sort(key=lambda z: z[0], reverse=True)
        win_sc = board[0][0]
        run_sc = board[1][0] if len(board) > 1 else 0
        if win_sc <= 0 or win_sc < run_sc + MARGIN:
            skips["catC_still_tied_human_review"] += 1
            defer_rows.append((aname, "still_tied:" +
                               ",".join("%s=%d" % (b[1][3], b[0])
                                        for b in board[:3])))
            continue
        _, w = board[0]
        pcid, pcn, repl = w[2], w[3], list(w[4])
    else:  # stem: choose parent by prose/title evidence over ALL classes
        board = []
        for cid, cn, cslug, feats in classes:
            sc = name_score(pl, cn)
            if re.search(r"(?<![a-z])" + re.escape(base(cn)) + r"(?![a-z])",
                         aname.lower()):
                sc += 3
            board.append((sc, cid, cn, feats))
        board.sort(key=lambda z: z[0], reverse=True)
        if board[0][0] <= 0 or board[0][0] < board[1][0] + MARGIN:
            skips["stem_no_clear_parent"] += 1
            defer_rows.append((aname, "stem_no_parent"))
            continue
        _, pcid, pcn, pfeats = board[0]
        repl = []
        for ph in pset:
            sp = stem_tokens(ph)
            for fid, fnt, lvl in pfeats:
                if fmatch(sp, fnt):
                    repl.append(fid)
                    break
        repl = list(dict.fromkeys(repl))
        if not repl:
            skips["stem_no_real_replace_after_stemming"] += 1
            defer_rows.append((aname, "stem_unmatched"))
            continue

    # adds[] — same extraction as bulk; must be non-empty
    adds = []
    for m in re.finditer(r"(?:this(?:\s+\w+){0,3}\s+replaces|\breplaces)\s",
                          prose, re.I):
        pre = prose[max(0, m.start() - 400):m.start()]
        hs = list(RE_ADDHDR.finditer(pre))
        if hs:
            h = hs[-1]
            nmh = h.group(1).strip()
            desc = pre[h.end():].strip()[:220]
            fid = slug(pcid.replace("__crb_", "")) + "_arch_" + slug(nmh)
            if not any(x["stats"]["id"] == fid[:60] for x in adds):
                adds.append({"resource_id": "class_feature", "stats": {
                    "id": fid[:60], "name": {"value": nmh[:80]},
                    "level": {"value": 1},
                    "description": {"value": (nmh + " — " + desc)[:300]},
                    "feature_category": {"value": "archetype"}}})
    adds = adds[:8]
    # "no actual mechanical change" = NOTHING changes. A replaces[]-only
    # archetype still removes base features (a real change) and is
    # consistent with bulk/Phase-2b which shipped empty-adds archetypes
    # (Aerial Assaulter, Trench Fighter). Skip only if BOTH are empty.
    if not adds and not repl:
        skips["empty_no_mechanical_change"] += 1
        defer_rows.append((aname, "empty_replaces_and_adds"))
        continue

    inst = {"resource_id": "class_archetype", "stats": {
        "id": aid, "name": {"value": aname}, "source": {"value": "crb"},
        "parent_class_id": {"value": pcid},
        "parent_class_name": {"value": pcn},
        "replaces": {"value": repl},
        "adds": {"value": adds},
        "prerequisites": {"value": []},
        "is_lore_only": {"value": False},
        "lore": {"value": prose}}}
    if APPLY:
        json.dump(inst, open(os.path.join(
            RI, "class_archetype_%s__crb_.rpg.json" % slug(aname)),
            "w", encoding="utf-8", newline="\n"), indent=2,
            ensure_ascii=False)
        os.remove(f)
    existing_arch.add(aid)
    shipped += 1
    ship_log.append((aname, pcn, bucket, len(repl), len(adds)))

print("MODE:", "APPLY" if APPLY else "DRY-RUN")
print("shipped:", shipped, "| skipped:", sum(skips.values()))
for k, v in skips.most_common():
    print("  skip[%s] = %d" % (k, v))
print("sample shipped:", ship_log[:14])
json.dump({"shipped": ship_log, "deferred": defer_rows},
          open(".local-notes/_phase2c_run.json", "w", encoding="utf-8"),
          indent=1, ensure_ascii=False)
