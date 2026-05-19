"""
Strip stray `lore` keys from resource_instances whose type's schema
does not declare a `lore` stat.

Background: the d20pfsrd lore scraper wrote `stats.lore` into every
matched instance, but the feat/spell/trait/archetype (legacy) resource
types do not declare a `lore` base/calc stat in their stats.rpgs.
The runtime silently drops undeclared stats — but the validator
(scripts/validate_resource_instances.py) flags them as
"Unknown stat: stats.lore".

For these types the canonical narrative field is `description`. The
original `description` content is the curated rules text; the
d20pfsrd lore was overlapping/duplicative. Safest course is to drop
the lore key; the original description is preserved untouched.

If a future session wants d20pfsrd-faithful content on these types,
modify scrape_d20pfsrd.py to write `description` instead of `lore`
for them. (And then decide whether to overwrite or concatenate.)

Discipline:
  - Idempotent: re-run does nothing
  - Reads existing schema (pf1e/system/resources/<t>/stats.rpgs) to
    decide which types are lore-aware; types with `lore` declared
    are NEVER touched
  - Dry-run by default; --apply to write
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INST_DIR = REPO / "pf1e" / "resource_instances"
RES_DIR = REPO / "pf1e" / "system" / "resources"

# Map filename prefix -> resource type. Order matters: longer prefixes first.
PREFIX_TO_TYPE = [
    ("race_lore_", "race"),
    ("race_", "race"),
    ("class_archetype_", "class_archetype"),
    ("class_prestige_", "class"),     # prestige uses class type
    ("class_lore_", "class"),
    ("class_", "class"),
    ("archetype_", "archetype"),
    ("feat_", "feat"),
    ("trait_", "trait"),
    ("spell_", "spell"),
]


def detect_type(fname):
    for px, ty in PREFIX_TO_TYPE:
        if fname.startswith(px):
            return ty
    return None


def type_has_lore_stat(t):
    """Read the type's stats.rpgs and check if it declares a lore stat."""
    f = RES_DIR / t / "stats.rpgs"
    if not f.is_file():
        return False
    txt = f.read_text(encoding="utf-8")
    return bool(re.search(r"^(?:base|calc)[^\n]+\blore\b", txt, re.MULTILINE))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    # Pre-check schema: which types accept lore?
    schema_status = {}
    for _, ty in PREFIX_TO_TYPE:
        if ty not in schema_status:
            schema_status[ty] = type_has_lore_stat(ty)
    print("Schema lore-stat declared by type:")
    for ty, has in sorted(schema_status.items()):
        print(f"  {ty}: {has}")
    print()

    counts = {
        "total": 0,
        "stripped": 0,
        "already_clean": 0,
        "lore_kept": 0,
        "type_unknown": 0,
        "fail": 0,
    }
    by_type = {}

    for fname in sorted(os.listdir(INST_DIR)):
        if not fname.endswith(".rpg.json"):
            continue
        counts["total"] += 1
        p = INST_DIR / fname
        try:
            raw = p.read_bytes().rstrip(b"\x00").rstrip().decode("utf-8")
            data = json.loads(raw)
        except Exception as e:
            counts["fail"] += 1
            print(f"FAIL parse {fname}: {e}", file=sys.stderr)
            continue
        t = detect_type(fname)
        if t is None:
            counts["type_unknown"] += 1
            continue
        stats = data.get("stats", {})
        if "lore" not in stats:
            counts["already_clean"] += 1
            continue
        if schema_status.get(t, False):
            counts["lore_kept"] += 1
            by_type.setdefault(t, [0, 0])[0] += 1  # kept
            continue
        # Strip lore key
        del stats["lore"]
        counts["stripped"] += 1
        by_type.setdefault(t, [0, 0])[1] += 1  # stripped
        if args.apply:
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        if args.verbose:
            print(f"strip {fname}")

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] total={counts['total']} "
          f"stripped={counts['stripped']} "
          f"lore_kept={counts['lore_kept']} "
          f"already_clean={counts['already_clean']} "
          f"type_unknown={counts['type_unknown']} "
          f"fail={counts['fail']}")
    print("\nPer-type breakdown (kept / stripped):")
    for t, (kept, stripped) in sorted(by_type.items()):
        print(f"  {t}: kept={kept} stripped={stripped}")


if __name__ == "__main__":
    main()
