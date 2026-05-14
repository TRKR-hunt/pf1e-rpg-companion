#!/usr/bin/env python3
"""Build Core Rulebook armor and shields.

Format: (id, name, category, cost_gp, armor_bonus, max_dex, acp, asf, speed_30, speed_20, weight_lb)
- category: light_armor / medium_armor / heavy_armor / shield
- asf: arcane spell failure %
"""
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

ARMORS = [
    # LIGHT ARMOR
    ("padded",      "Padded",        "light_armor", 5,    1,  8,  0,  5,  30, 20, 10),
    ("leather",     "Leather",       "light_armor", 10,   2,  6,  0, 10,  30, 20, 15),
    ("studded_leather", "Studded Leather", "light_armor", 25, 3, 5, -1, 15, 30, 20, 20),
    ("chain_shirt", "Chain Shirt",   "light_armor", 100,  4,  4, -2, 20,  30, 20, 25),
    # MEDIUM ARMOR
    ("hide",        "Hide",          "medium_armor", 15,  4,  4, -3, 20,  20, 15, 25),
    ("scale_mail",  "Scale Mail",    "medium_armor", 50,  5,  3, -4, 25,  20, 15, 30),
    ("chainmail",   "Chainmail",     "medium_armor", 150, 6,  2, -5, 30,  20, 15, 40),
    ("breastplate", "Breastplate",   "medium_armor", 200, 6,  3, -4, 25,  20, 15, 30),
    # HEAVY ARMOR
    ("splint_mail", "Splint Mail",   "heavy_armor", 200,  7,  0, -7, 40,  20, 15, 45),
    ("banded_mail", "Banded Mail",   "heavy_armor", 250,  7,  1, -6, 35,  20, 15, 35),
    ("half_plate",  "Half-Plate",    "heavy_armor", 600,  8,  0, -7, 40,  20, 15, 50),
    ("full_plate",  "Full Plate",    "heavy_armor", 1500, 9,  1, -6, 35,  20, 15, 50),
    # SHIELDS
    ("buckler",          "Buckler",          "shield", 5,   1, None, -1,  5, None, None, 5),
    ("shield_light_wood","Shield, Light Wooden", "shield", 3, 1, None, -1, 5, None, None, 5),
    ("shield_light_steel","Shield, Light Steel", "shield", 9, 1, None, -1, 5, None, None, 6),
    ("shield_heavy_wood","Shield, Heavy Wooden", "shield", 7, 2, None, -2, 15, None, None, 10),
    ("shield_heavy_steel","Shield, Heavy Steel", "shield", 20, 2, None, -2, 15, None, None, 15),
    ("shield_tower",      "Shield, Tower",     "shield", 30, 4, 2, -10, 50, None, None, 45),
]


def build_armor_json(a):
    (aid, name, cat, cost, ab, mxd, acp, asf, sp30, sp20, wt) = a
    return {
        "resource_id": "armor",
        "stats": {
            "id": f"{aid}__crb_",
            "name": {"value": name},
            "source": {"value": "crb"},
            "category": {"value": cat},
            "cost_gp": {"value": cost},
            "armor_bonus": {"value": ab},
            "max_dex_bonus": {"value": mxd if mxd is not None else 99},
            "armor_check_penalty": {"value": acp},
            "arcane_spell_failure": {"value": asf},
            "speed_30_ft_in_armor": {"value": sp30},
            "speed_20_ft_in_armor": {"value": sp20},
            "weight_lb": {"value": wt},
        },
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for a in ARMORS:
        d = build_armor_json(a)
        path = OUT_DIR / f"armor_{d['stats']['id']}.rpg.json"
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    print(f"Done: {len(ARMORS)} armors/shields")


if __name__ == "__main__":
    main()
