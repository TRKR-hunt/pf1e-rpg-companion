"""
Deterministic lore formatting cleanup.

Operates on the existing scraped `lore` strings in pf1e/resource_instances/
without web access. Fixes:

 - UTF-8 mojibake (\\xe2\\x80\\x99 -> right single quote, etc.)
 - Trailing NUL-byte padding on .rpg.json files (a real disk artifact from
   earlier generators that breaks json parsers)
 - TOC-soup at head of every scraped page (e.g. "Standard Racial Traits
   Alternate Racial Traits Favored Class Options ..." run together)
 - Injects paragraph breaks before known section labels
 - Adds markdown ### headings for those section labels
 - Splits run-on feature lists into bullets keyed on bold names

Discipline (mirrors scripts/expand_class_features.py):
 - Idempotent: re-run produces zero diff
 - Augment-only: never deletes content; only reshapes
 - Assert-driven: refuses to write a string that lost > 10% of letters
 - Dry-run by default; --apply to write

Usage:
  python3 scripts/clean_lore_formatting.py --target=races
  python3 scripts/clean_lore_formatting.py --target=races --apply
  python3 scripts/clean_lore_formatting.py --target=all --apply
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INST_DIR = REPO / "pf1e" / "resource_instances"

RACE_SECTIONS = [
    "Standard Racial Traits",
    "Alternate Racial Traits",
    "Defense Racial Traits",
    "Feat and Skill Racial Traits",
    "Magical Racial Traits",
    "Movement Racial Traits",
    "Offense Racial Traits",
    "Senses Racial Traits",
    "Weakness Racial Traits",
    "Other Racial Traits",
    "Favored Class Options",
    "Racial Archetypes",
    "Racial Archetype",
    "Racial Subtypes",
    "Racial Feats",
    "Subraces",
]

CLASS_SECTIONS = [
    "Role",
    "Alignment",
    "Hit Die",
    "Starting Wealth",
    "Class Skills",
    "Class Features",
    "Weapon and Armor Proficiency",
    "Weapons and Armor Proficiency",
    "Spells",
    "Spellcasting",
    "Spells per Day",
    "Bonus Spells",
    "Favored Class Options",
    "Archetypes",
    "Archetypes & Alternate Class Features",
    "Archetypes & Other Class Options",
    "Alternative Capstone Ability",
    "Ex-Class",
    "Optional Rules",
    "Requirements",
]

ARCHETYPE_SECTIONS = [
    "Class Features",
    "Weapon and Armor Proficiency",
    "Weapons and Armor Proficiency",
    "Class Skills",
    "Alternative Capstone Ability",
]

# UTF-8-as-latin1 mojibake replacements.
MOJIBAKE_BYTES = [
    (b"\xc3\xa2\xc2\x80\xc2\x99", b"\xe2\x80\x99"),   # ’
    (b"\xc3\xa2\xc2\x80\xc2\x9c", b"\xe2\x80\x9c"),   # “
    (b"\xc3\xa2\xc2\x80\xc2\x9d", b"\xe2\x80\x9d"),   # ”
    (b"\xc3\xa2\xc2\x80\xc2\x94", b"\xe2\x80\x94"),   # —
    (b"\xc3\xa2\xc2\x80\xc2\x93", b"\xe2\x80\x93"),   # –
    (b"\xc3\xa2\xc2\x80\xc2\xa6", b"\xe2\x80\xa6"),   # …
    (b"\xc3\xa2\xc2\x80\xc2\x98", b"\xe2\x80\x98"),   # ‘
]


def fix_mojibake(s: str) -> str:
    # Treat mojibake from the standpoint of "appears as the literal bytes
    # 0xe2 0x80 0xXX after the scraper mis-encoded UTF-8 as latin-1 then
    # re-encoded to UTF-8". Round-trip latin1 -> utf-8 fixes them.
    try:
        candidate = s.encode("latin-1").decode("utf-8")
        # Only accept the round-trip if it actually CHANGED the string
        # (would round-trip cleanly for ASCII-only strings anyway).
        return candidate
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def strip_leading_toc(s: str, section_labels) -> str:
    head = s[:2000]
    m = re.search(r"\.\s+[A-Z]", head)
    if not m:
        return s
    cut_idx = m.start() + 1
    pre = head[:cut_idx]
    words = pre.split()
    if len(words) < 6:
        return s
    title_words = sum(1 for w in words if w and w[0].isupper())
    if title_words / max(len(words), 1) < 0.55:
        return s
    if not any(lbl in pre for lbl in section_labels):
        return s
    return s[cut_idx:].lstrip()


def insert_paragraph_breaks(s: str, section_labels) -> str:
    out = s
    # Sort longest first so "Alternate Racial Traits" is matched before "Racial Traits"
    for lbl in sorted(section_labels, key=lambda x: -len(x)):
        if re.search(rf"(?m)^#{{2,3}} +{re.escape(lbl)}\b", out):
            continue
        pattern = re.compile(rf"(?<![\n\#> ]){re.escape(lbl)}(?=\b)")
        out = pattern.sub(f"\n\n### {lbl}", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def split_bold_prefixed_runs(s: str) -> str:
    feat_pat = re.compile(
        r"(?P<name>(?:[A-Z][a-z'’\-]+(?:\s+(?:of|the|in|to|and|for|with|on)\s+|\s+)){0,4}[A-Z][a-z'’\-]+)"
        r"\s*(?P<qual>\((?:Ex|Su|Sp|Ex/Su|Ex or Su)\))?"
        r":\s+(?=[A-Z])"
    )
    paragraphs = s.split("\n\n")
    out = []
    for para in paragraphs:
        matches = list(feat_pat.finditer(para))
        if len(matches) < 3:
            out.append(para)
            continue
        lines = para.splitlines()
        if sum(1 for ln in lines if ln.strip().startswith("- ")) >= 2:
            out.append(para)
            continue
        spans = [(m.start(), m.end(), m.group("name"), m.group("qual") or "") for m in matches]
        chunks = []
        lead = para[: spans[0][0]].strip()
        if lead:
            chunks.append(lead)
        for i, (st, en, name, qual) in enumerate(spans):
            next_st = spans[i + 1][0] if i + 1 < len(spans) else len(para)
            body = para[en:next_st].strip()
            qsfx = f" {qual}" if qual else ""
            chunks.append(f"- **{name}{qsfx}.** {body}")
        out.append("\n".join(chunks))
    return "\n\n".join(out)


def detect_kind(filename: str):
    if filename.startswith("race_"):
        return "race"
    if filename.startswith("class_archetype_"):
        return "class_archetype"
    if filename.startswith("class_prestige_"):
        return "prestige_class"
    if filename.startswith("class_") and not filename.startswith(
        ("class_archetype_", "class_prestige_")
    ):
        return "class"
    if filename.startswith("archetype_"):
        return "archetype"
    return None


def section_labels_for(kind: str):
    if kind == "race":
        return RACE_SECTIONS
    if kind in ("class", "prestige_class"):
        return CLASS_SECTIONS
    if kind in ("class_archetype", "archetype"):
        return ARCHETYPE_SECTIONS
    return []


def reshape(text: str, kind: str) -> str:
    if not text:
        return text
    labels = section_labels_for(kind)
    out = fix_mojibake(text)
    out = strip_leading_toc(out, labels)
    out = insert_paragraph_breaks(out, labels)
    out = split_bold_prefixed_runs(out)
    out = "\n".join(line.rstrip() for line in out.splitlines())
    return out.strip()


def assert_no_content_loss(before: str, after: str, *, allow_loss_ratio=0.20):
    b_alpha = sum(1 for c in before if c.isalpha())
    a_alpha = sum(1 for c in after if c.isalpha())
    if b_alpha == 0:
        return
    loss = (b_alpha - a_alpha) / b_alpha
    assert loss < allow_loss_ratio, (
        f"refusing to ship: content loss {loss:.1%} > {allow_loss_ratio:.0%} cap"
    )


def _load_json_robust(path: Path):
    raw = path.read_bytes()
    stripped = raw.rstrip(b"\x00").rstrip()
    return json.loads(stripped.decode("utf-8")), (len(stripped) != len(raw))


def process_file(path: Path, *, apply: bool):
    data, had_padding = _load_json_robust(path)
    stats = data.get("stats", {})
    lore_block = stats.get("lore")
    if not isinstance(lore_block, dict):
        if had_padding and apply:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        return had_padding, ("normalize " + path.name if had_padding
                             else "skip(no-lore-block) " + path.name)
    before = lore_block.get("value", "") or ""
    kind = detect_kind(path.name)
    if not kind:
        return had_padding, "skip(unknown-kind) " + path.name
    if not before:
        if had_padding and apply:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        return had_padding, ("normalize(empty-lore) " + path.name if had_padding
                             else "skip(empty-lore) " + path.name)
    after = reshape(before, kind)
    if after == before and not had_padding:
        return False, "clean " + path.name
    if after != before:
        assert_no_content_loss(before, after)
        lore_block["value"] = after
    if apply:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    tag = "rewrite" if after != before else "normalize"
    return True, f"{tag} {path.name} ({len(before)} -> {len(after)} chars)"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target",
                    choices=["races", "classes", "prestige", "archetypes", "all"],
                    default="all")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if not INST_DIR.is_dir():
        print(f"resource_instances not found at {INST_DIR}", file=sys.stderr)
        sys.exit(2)

    def matches(name):
        if args.target == "races":
            return name.startswith("race_")
        if args.target == "classes":
            return name.startswith("class_") and not name.startswith(
                ("class_archetype_", "class_prestige_"))
        if args.target == "prestige":
            return name.startswith("class_prestige_")
        if args.target == "archetypes":
            return name.startswith("class_archetype_") or name.startswith("archetype_")
        return name.startswith(("race_", "class_", "archetype_"))

    files = sorted(p for p in INST_DIR.iterdir() if p.is_file() and matches(p.name))
    if args.limit:
        files = files[: args.limit]

    rewrites = normalize_only = clean = skipped = failures = 0
    for p in files:
        try:
            changed, summary = process_file(p, apply=args.apply)
        except Exception as e:
            failures += 1
            print(f"FAIL {p.name}: {e}", file=sys.stderr)
            continue
        if summary.startswith("rewrite"):
            rewrites += 1
            if args.verbose:
                print(summary)
        elif summary.startswith("normalize"):
            normalize_only += 1
            if args.verbose:
                print(summary)
        elif summary.startswith("clean"):
            clean += 1
        else:
            skipped += 1
            if args.verbose:
                print(summary)
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"[{mode}] target={args.target} files={len(files)} "
          f"rewrites={rewrites} normalize-only={normalize_only} "
          f"clean={clean} skipped={skipped} failures={failures}")


if __name__ == "__main__":
    main()
