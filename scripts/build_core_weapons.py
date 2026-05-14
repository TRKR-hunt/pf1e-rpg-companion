#!/usr/bin/env python3
"""Build Core Rulebook weapons.

Format: (id, name, category, cost_gp, dmg_S, dmg_M, crit, range_ft, weight_lb, type, special)
- category: simple_light / simple_oneh / simple_twoh / simple_ranged /
            martial_light / martial_oneh / martial_twoh / martial_ranged /
            exotic_light / exotic_oneh / exotic_twoh / exotic_ranged
- type: B / P / S or combos like "B and P"
"""
import json
import re
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

# Compact CRB weapons table. Damage values for medium creatures.
# For brevity we encode the canonical Core list. Easy to extend.
WEAPONS = [
    # SIMPLE - UNARMED / LIGHT MELEE
    ("unarmed_strike", "Unarmed Strike", "simple_unarmed", 0, "1d2", "1d3", "20/×2", 0, 0, "B", "nonlethal"),
    ("dagger", "Dagger", "simple_light", 2, "1d3", "1d4", "19-20/×2", 10, 1, "P or S", ""),
    ("dagger_punching", "Dagger, Punching", "simple_light", 2, "1d3", "1d4", "×3", 0, 1, "P", ""),
    ("gauntlet_spiked", "Gauntlet, Spiked", "simple_light", 5, "1d3", "1d4", "×2", 0, 1, "P", ""),
    ("mace_light", "Mace, Light", "simple_light", 5, "1d4", "1d6", "×2", 0, 4, "B", ""),
    ("sickle", "Sickle", "simple_light", 6, "1d4", "1d6", "×2", 0, 2, "S", "trip"),
    # SIMPLE - ONE-HANDED MELEE
    ("club", "Club", "simple_oneh", 0, "1d4", "1d6", "×2", 10, 3, "B", ""),
    ("mace_heavy", "Mace, Heavy", "simple_oneh", 12, "1d6", "1d8", "×2", 0, 8, "B", ""),
    ("morningstar", "Morningstar", "simple_oneh", 8, "1d6", "1d8", "×2", 0, 6, "B and P", ""),
    ("shortspear", "Shortspear", "simple_oneh", 1, "1d4", "1d6", "×2", 20, 3, "P", ""),
    # SIMPLE - TWO-HANDED MELEE
    ("longspear", "Longspear", "simple_twoh", 5, "1d6", "1d8", "×3", 0, 9, "P", "brace, reach"),
    ("quarterstaff", "Quarterstaff", "simple_twoh", 0, "1d4/1d4", "1d6/1d6", "×2", 0, 4, "B", "double, monk"),
    ("spear", "Spear", "simple_twoh", 2, "1d6", "1d8", "×3", 20, 6, "P", "brace"),
    # SIMPLE - RANGED
    ("crossbow_heavy", "Crossbow, Heavy", "simple_ranged", 50, "1d8", "1d10", "19-20/×2", 120, 8, "P", ""),
    ("crossbow_light", "Crossbow, Light", "simple_ranged", 35, "1d6", "1d8", "19-20/×2", 80, 4, "P", ""),
    ("dart", "Dart", "simple_ranged", 0.5, "1d3", "1d4", "×2", 20, 0.5, "P", ""),
    ("javelin", "Javelin", "simple_ranged", 1, "1d4", "1d6", "×2", 30, 2, "P", ""),
    ("sling", "Sling", "simple_ranged", 0, "1d3", "1d4", "×2", 50, 0, "B", ""),
    # MARTIAL - LIGHT MELEE
    ("axe_throwing", "Axe, Throwing", "martial_light", 8, "1d4", "1d6", "×2", 10, 2, "S", ""),
    ("hammer_light", "Hammer, Light", "martial_light", 1, "1d3", "1d4", "×2", 20, 2, "B", ""),
    ("handaxe", "Handaxe", "martial_light", 6, "1d4", "1d6", "×3", 0, 3, "S", ""),
    ("kukri", "Kukri", "martial_light", 8, "1d3", "1d4", "18-20/×2", 0, 2, "S", ""),
    ("pick_light", "Pick, Light", "martial_light", 4, "1d3", "1d4", "×4", 0, 3, "P", ""),
    ("sap", "Sap", "martial_light", 1, "1d4", "1d6", "×2", 0, 2, "B", "nonlethal"),
    ("shield_light", "Shield, Light (bash)", "martial_light", 0, "1d2", "1d3", "×2", 0, 0, "B", ""),
    ("spiked_armor", "Spiked Armor", "martial_light", 0, "1d4", "1d6", "×2", 0, 0, "P", ""),
    ("spiked_shield_light", "Spiked Shield, Light", "martial_light", 0, "1d3", "1d4", "×2", 0, 0, "P", ""),
    ("starknife", "Starknife", "martial_light", 24, "1d3", "1d4", "×3", 20, 3, "P", ""),
    ("sword_short", "Sword, Short", "martial_light", 10, "1d4", "1d6", "19-20/×2", 0, 2, "P", ""),
    # MARTIAL - ONE-HANDED MELEE
    ("battleaxe", "Battleaxe", "martial_oneh", 10, "1d6", "1d8", "×3", 0, 6, "S", ""),
    ("flail", "Flail", "martial_oneh", 8, "1d6", "1d8", "×2", 0, 5, "B", "disarm, trip"),
    ("longsword", "Longsword", "martial_oneh", 15, "1d6", "1d8", "19-20/×2", 0, 4, "S", ""),
    ("pick_heavy", "Pick, Heavy", "martial_oneh", 8, "1d4", "1d6", "×4", 0, 6, "P", ""),
    ("rapier", "Rapier", "martial_oneh", 20, "1d4", "1d6", "18-20/×2", 0, 2, "P", ""),
    ("scimitar", "Scimitar", "martial_oneh", 15, "1d4", "1d6", "18-20/×2", 0, 4, "S", ""),
    ("shield_heavy", "Shield, Heavy (bash)", "martial_oneh", 0, "1d3", "1d4", "×2", 0, 0, "B", ""),
    ("spiked_shield_heavy", "Spiked Shield, Heavy", "martial_oneh", 0, "1d4", "1d6", "×2", 0, 0, "P", ""),
    ("trident", "Trident", "martial_oneh", 15, "1d6", "1d8", "×2", 10, 4, "P", "brace"),
    ("warhammer", "Warhammer", "martial_oneh", 12, "1d6", "1d8", "×3", 0, 5, "B", ""),
    # MARTIAL - TWO-HANDED MELEE
    ("falchion", "Falchion", "martial_twoh", 75, "1d6", "2d4", "18-20/×2", 0, 8, "S", ""),
    ("glaive", "Glaive", "martial_twoh", 8, "1d8", "1d10", "×3", 0, 10, "S", "reach"),
    ("greataxe", "Greataxe", "martial_twoh", 20, "1d10", "1d12", "×3", 0, 12, "S", ""),
    ("greatclub", "Greatclub", "martial_twoh", 5, "1d8", "1d10", "×2", 0, 8, "B", ""),
    ("flail_heavy", "Flail, Heavy", "martial_twoh", 15, "1d8", "1d10", "19-20/×2", 0, 10, "B", "disarm, trip"),
    ("greatsword", "Greatsword", "martial_twoh", 50, "1d10", "2d6", "19-20/×2", 0, 8, "S", ""),
    ("guisarme", "Guisarme", "martial_twoh", 9, "1d6", "2d4", "×3", 0, 12, "S", "reach, trip"),
    ("halberd", "Halberd", "martial_twoh", 10, "1d8", "1d10", "×3", 0, 12, "P or S", "brace, trip"),
    ("lance", "Lance", "martial_twoh", 10, "1d6", "1d8", "×3", 0, 10, "P", "reach"),
    ("ranseur", "Ranseur", "martial_twoh", 10, "1d6", "2d4", "×3", 0, 12, "P", "disarm, reach"),
    ("scythe", "Scythe", "martial_twoh", 18, "1d6", "2d4", "×4", 0, 10, "P or S", "trip"),
    # MARTIAL - RANGED
    ("longbow", "Longbow", "martial_ranged", 75, "1d6", "1d8", "×3", 100, 3, "P", ""),
    ("longbow_composite", "Longbow, Composite", "martial_ranged", 100, "1d6", "1d8", "×3", 110, 3, "P", "+Str bonus"),
    ("shortbow", "Shortbow", "martial_ranged", 30, "1d4", "1d6", "×3", 60, 2, "P", ""),
    ("shortbow_composite", "Shortbow, Composite", "martial_ranged", 75, "1d4", "1d6", "×3", 70, 2, "P", "+Str bonus"),
    # EXOTIC (subset of core)
    ("bastard_sword", "Bastard Sword", "exotic_oneh", 35, "1d8", "1d10", "19-20/×2", 0, 6, "S", ""),
    ("dwarven_waraxe", "Dwarven Waraxe", "exotic_oneh", 30, "1d8", "1d10", "×3", 0, 8, "S", ""),
    ("whip", "Whip", "exotic_oneh", 1, "1d2", "1d3", "×2", 0, 2, "S", "disarm, nonlethal, reach, trip"),
    ("kama", "Kama", "exotic_light", 2, "1d4", "1d6", "×2", 0, 2, "S", "monk, trip"),
    ("nunchaku", "Nunchaku", "exotic_light", 2, "1d4", "1d6", "×2", 0, 2, "B", "disarm, monk"),
    ("sai", "Sai", "exotic_light", 1, "1d3", "1d4", "×2", 0, 1, "B", "disarm, monk"),
    ("siangham", "Siangham", "exotic_light", 3, "1d4", "1d6", "×2", 0, 1, "P", "monk"),
    ("shuriken", "Shuriken", "exotic_ranged", 1, "1d1", "1d2", "×2", 10, 0.5, "P", "monk"),
    ("hand_crossbow", "Crossbow, Hand", "exotic_ranged", 100, "1d3", "1d4", "19-20/×2", 30, 2, "P", ""),
    ("crossbow_repeating_heavy", "Crossbow, Repeating Heavy", "exotic_ranged", 400, "1d8", "1d10", "19-20/×2", 120, 12, "P", ""),
    ("crossbow_repeating_light", "Crossbow, Repeating Light", "exotic_ranged", 250, "1d6", "1d8", "19-20/×2", 80, 6, "P", ""),
    ("net", "Net", "exotic_ranged", 20, "—", "—", "—", 10, 6, "—", "entangle"),
]


_DAMAGE_TYPE_ABBREV = {"B": "bludgeoning", "P": "piercing", "S": "slashing"}


def _normalize_damage_type(dtype: str) -> str:
    """Return a single canonical `damage_types` enum id. The PF1e table also
    uses combined values like 'P or S' / 'B and P' for weapons that can deal
    either of two types — we keep only the primary (first listed) here, since
    the schema declares `damage_type` as a single string and the runtime does
    `enumeratedName(damage_types, id = ...)` lookups. Composite-damage support
    is a future task (would require `damage_type` becoming `string[]` and the
    display view splitting).
    Non-damaging weapons (Net's '—') return '' (empty), and the validator
    skips empty-string enum checks."""
    if not dtype:
        return ""
    raw = dtype.strip()
    parts = re.split(r"\s*(?:,|/|or|and)\s*", raw, flags=re.IGNORECASE)
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Filter out the em-dash / hyphen sentinels for non-damaging weapons.
        if p in ("—", "-", "--"):
            continue
        return _DAMAGE_TYPE_ABBREV.get(p.upper(), p.lower())
    return ""


def build_weapon_json(w):
    (wid, name, cat, cost, dS, dM, crit, rng, wt, dtype, special) = w
    return {
        "resource_id": "weapon",
        "stats": {
            "id": f"{wid}__crb_",
            "name": {"value": name},
            "source": {"value": "crb"},
            "category": {"value": cat},
            "cost_gp": {"value": cost},
            "damage_small": {"value": dS},
            "damage": {"value": dM},
            "critical": {"value": crit},
            "range_increment_ft": {"value": rng},
            "weight_lb": {"value": wt},
            "damage_type": {"value": _normalize_damage_type(dtype)},
            "special": {"value": special},
        },
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for w in WEAPONS:
        d = build_weapon_json(w)
        path = OUT_DIR / f"weapon_{d['stats']['id']}.rpg.json"
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    print(f"Done: {len(WEAPONS)} weapons")


if __name__ == "__main__":
    main()
