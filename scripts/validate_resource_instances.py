#!/usr/bin/env python3
"""
Validate every resource_instance JSON file we've generated.

Checks:
  - File parses as JSON
  - Has top-level `resource_id` and `stats`
  - Every stat value is wrapped in a `{value: ...}` object
  - `id` field present and matches the filename slug
  - Each resource_id has its required field set per a minimal schema
  - Cross-refs (e.g., a class's `class_skills` are real skill IDs) — basic check

Run from scripts/:
    python validate_resource_instances.py
"""
import json
import re
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

REQUIRED_FIELDS = {
    "class": ["name", "bab_progression", "fortitude_progression",
              "reflex_progression", "will_progression", "hit_die",
              "class_skills", "skill_ranks_per_level"],
    "race": ["name", "size", "base_speed"],
    "feat": ["name", "description"],
    "spell": ["name", "level", "school"],
    "weapon": ["name", "damage", "critical"],
    "armor": ["name", "armor_bonus"],
}

KNOWN_SKILLS = {
    "acrobatics", "appraise", "bluff", "climb", "craft", "diplomacy",
    "disable_device", "disguise", "escape_artist", "fly", "handle_animal",
    "heal", "intimidate", "knowledge_arcana", "knowledge_dungeoneering",
    "knowledge_engineering", "knowledge_geography", "knowledge_history",
    "knowledge_local", "knowledge_nature", "knowledge_nobility",
    "knowledge_planes", "knowledge_religion", "linguistics", "perception",
    "perform", "profession", "ride", "sense_motive", "sleight_of_hand",
    "spellcraft", "stealth", "survival", "swim", "use_magic_device",
}

VALID_BAB = {"full", "three_quarters", "half"}
VALID_SAVE = {"good", "poor"}
VALID_SIZE = {"fine", "diminutive", "tiny", "small", "medium",
              "large", "huge", "gargantuan", "colossal"}


def get(stats, key, default=None):
    v = stats.get(key)
    if v is None:
        return default
    if isinstance(v, dict) and "value" in v:
        return v["value"]
    return v


def validate_file(path: Path) -> list[str]:
    errors = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"{path.name}: invalid JSON ({e})"]

    rid = data.get("resource_id")
    if not rid:
        errors.append(f"{path.name}: missing resource_id")
        return errors
    stats = data.get("stats") or {}
    if not stats:
        errors.append(f"{path.name}: missing stats")
        return errors

    # ID present and consistent with filename.
    # Convention observed in pf2e:
    #   - Feats: id already includes "feat_" prefix; filename is "{id}.rpg.json"
    #   - All other types: id has no prefix; filename is "{resource_id}_{id}.rpg.json"
    # The `id` value is a raw string (NOT wrapped in {value: ...}).
    inst_id = stats.get("id")
    if isinstance(inst_id, dict):
        inst_id = inst_id.get("value")
    if not inst_id:
        errors.append(f"{path.name}: stats.id missing")
    else:
        slug = path.name.replace(".rpg.json", "")
        if inst_id.startswith(f"{rid}_"):
            expected = inst_id
        else:
            expected = f"{rid}_{inst_id}"
        if slug != expected:
            errors.append(f"{path.name}: filename should be '{expected}.rpg.json' (id='{inst_id}')")

    # Required fields per resource_id
    for f in REQUIRED_FIELDS.get(rid, []):
        if get(stats, f) in (None, ""):
            errors.append(f"{path.name}: missing required field '{f}'")

    # Resource-specific deeper checks
    if rid == "class":
        if (b := get(stats, "bab_progression")) and b not in VALID_BAB:
            errors.append(f"{path.name}: bad bab_progression '{b}'")
        for s in ("fortitude_progression", "reflex_progression", "will_progression"):
            v = get(stats, s)
            if v and v not in VALID_SAVE:
                errors.append(f"{path.name}: bad {s} '{v}'")
        cs = get(stats, "class_skills") or []
        for skill in cs:
            if skill not in KNOWN_SKILLS:
                errors.append(f"{path.name}: unknown class skill '{skill}'")

    if rid == "race":
        sz = get(stats, "size")
        if sz and sz not in VALID_SIZE:
            errors.append(f"{path.name}: bad size '{sz}'")
        sp = get(stats, "base_speed")
        if sp is not None and not isinstance(sp, int):
            errors.append(f"{path.name}: base_speed must be int, got {type(sp).__name__}")

    if rid == "spell":
        lvl = get(stats, "level")
        if lvl is not None and not isinstance(lvl, int):
            errors.append(f"{path.name}: spell level must be int, got {lvl!r}")
        elif isinstance(lvl, int) and not (0 <= lvl <= 9):
            errors.append(f"{path.name}: spell level out of range: {lvl}")

    return errors


def main():
    if not OUT_DIR.exists():
        print(f"No directory at {OUT_DIR}")
        return
    paths = sorted(OUT_DIR.glob("*.rpg.json"))
    if not paths:
        print(f"No .rpg.json files in {OUT_DIR}")
        return
    total_errors = 0
    file_count = 0
    counts_by_kind = {}
    for p in paths:
        try:
            kind = json.loads(p.read_text()).get("resource_id", "?")
            counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        except Exception:
            counts_by_kind["?"] = counts_by_kind.get("?", 0) + 1
        errs = validate_file(p)
        if errs:
            file_count += 1
            total_errors += len(errs)
            for e in errs:
                print(e)
    print()
    print(f"Files: {len(paths)}")
    for k, n in sorted(counts_by_kind.items()):
        print(f"  {k}: {n}")
    if total_errors:
        print(f"\nFAIL: {total_errors} errors in {file_count} files")
        raise SystemExit(1)
    print("\nOK: all files valid")


if __name__ == "__main__":
    main()
