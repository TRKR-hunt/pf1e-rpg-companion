#!/usr/bin/env python3
"""Build all 7 Core Rulebook races for PF1e."""
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

RACES = [
    {
        "id": "dwarf", "name": "Dwarf",
        "size": "medium", "base_speed": 20,
        "type": "humanoid (dwarf)",
        "ability_mods": {"constitution": 2, "wisdom": 2, "charisma": -2},
        "starting_languages": ["common", "dwarven"],
        "bonus_languages_note": "Giant, Gnome, Goblin, Orc, Terran, Undercommon.",
        "traits": [
            ("Slow and Steady", "Dwarves have a base speed of 20 ft but their speed is never modified by armor or encumbrance."),
            ("Darkvision", "Dwarves can see in the dark up to 60 ft."),
            ("Defensive Training", "+4 dodge bonus to AC vs creatures of the giant subtype."),
            ("Greed", "+2 racial bonus on Appraise checks to determine the price of nonmagical goods that contain precious metals or gemstones."),
            ("Hatred", "+1 racial bonus on attack rolls against humanoid creatures of the orc and goblinoid subtypes."),
            ("Hardy", "+2 racial bonus on saving throws against poison, spells, and spell-like abilities."),
            ("Stability", "+4 racial bonus on CMD vs bull rush or trip while standing on the ground."),
            ("Stonecunning", "+2 racial bonus on Perception checks to notice unusual stonework."),
            ("Weapon Familiarity", "Proficient with battleaxes, heavy picks, and warhammers; treat any weapon with 'dwarven' in name as martial."),
        ],
    },
    {
        "id": "elf", "name": "Elf",
        "size": "medium", "base_speed": 30,
        "type": "humanoid (elf)",
        "ability_mods": {"dexterity": 2, "intelligence": 2, "constitution": -2},
        "starting_languages": ["common", "elven"],
        "bonus_languages_note": "Celestial, Draconic, Gnoll, Gnome, Goblin, Orc, Sylvan.",
        "traits": [
            ("Low-Light Vision", "Elves can see twice as far as humans in dim light."),
            ("Elven Immunities", "Immune to magic sleep effects; +2 vs enchantment spells and effects."),
            ("Elven Magic", "+2 racial bonus on caster level checks to overcome SR; +2 to Spellcraft to identify magic item properties."),
            ("Keen Senses", "+2 racial bonus on Perception checks."),
            ("Weapon Familiarity", "Proficient with longbows, longswords, rapiers, and shortbows; treat any weapon with 'elven' in name as martial."),
        ],
    },
    {
        "id": "gnome", "name": "Gnome",
        "size": "small", "base_speed": 20,
        "type": "humanoid (gnome)",
        "ability_mods": {"constitution": 2, "charisma": 2, "strength": -2},
        "starting_languages": ["common", "gnome", "sylvan"],
        "bonus_languages_note": "Draconic, Dwarven, Elven, Giant, Goblin, Orc.",
        "traits": [
            ("Defensive Training", "+4 dodge bonus to AC vs creatures of the giant subtype."),
            ("Gnome Magic", "+1 to DC of illusion spells; SLAs (1/day): dancing lights, ghost sound, prestidigitation, speak with animals (Cha 11+)."),
            ("Hatred", "+1 racial bonus on attack rolls vs humanoid creatures of the reptilian and goblinoid subtypes."),
            ("Illusion Resistance", "+2 racial saving throw bonus against illusion spells and effects."),
            ("Keen Senses", "+2 racial bonus on Perception checks."),
            ("Low-Light Vision", ""),
            ("Obsessive", "+2 racial bonus on a Craft or Profession skill of their choice."),
            ("Small", "+1 size to AC and attack; +4 size to Stealth; -1 CMB/CMD; lifting/carrying 3/4 of medium."),
            ("Weapon Familiarity", "Treat any weapon with 'gnome' in name as martial."),
        ],
    },
    {
        "id": "half-elf", "name": "Half-Elf",
        "size": "medium", "base_speed": 30,
        "type": "humanoid (human, elf)",
        "ability_mods": {"floating": 2},
        "starting_languages": ["common", "elven"],
        "bonus_languages_note": "Any (except secret languages).",
        "traits": [
            ("Adaptability", "Half-elves gain Skill Focus as a bonus feat at 1st level."),
            ("Elf Blood", "Counts as both elf and human for any effect related to race."),
            ("Elven Immunities", "Immune to magic sleep; +2 vs enchantment."),
            ("Keen Senses", "+2 racial bonus on Perception."),
            ("Low-Light Vision", ""),
            ("Multitalented", "Choose two favored classes; gain +1 hp or +1 skill rank when leveling up either."),
        ],
    },
    {
        "id": "half-orc", "name": "Half-Orc",
        "size": "medium", "base_speed": 30,
        "type": "humanoid (human, orc)",
        "ability_mods": {"floating": 2},
        "starting_languages": ["common", "orc"],
        "bonus_languages_note": "Abyssal, Draconic, Giant, Gnoll, Goblin.",
        "traits": [
            ("Darkvision", "Half-orcs can see in the dark up to 60 ft."),
            ("Intimidating", "+2 racial bonus on Intimidate."),
            ("Orc Blood", "Counts as both human and orc for any effect related to race."),
            ("Orc Ferocity", "Once per day, when brought below 0 HP but not killed, can fight on for one more round as if disabled."),
            ("Weapon Familiarity", "Proficient with greataxes and falchions; treat any weapon with 'orc' in name as martial."),
        ],
    },
    {
        "id": "halfling", "name": "Halfling",
        "size": "small", "base_speed": 20,
        "type": "humanoid (halfling)",
        "ability_mods": {"dexterity": 2, "charisma": 2, "strength": -2},
        "starting_languages": ["common", "halfling"],
        "bonus_languages_note": "Dwarven, Elven, Gnome, Goblin.",
        "traits": [
            ("Fearless", "+2 racial bonus on saves vs fear (stacks with Halfling Luck)."),
            ("Halfling Luck", "+1 racial bonus on all saving throws."),
            ("Keen Senses", "+2 racial bonus on Perception."),
            ("Sure-Footed", "+2 racial bonus on Acrobatics and Climb."),
            ("Weapon Familiarity", "Proficient with slings; treat any weapon with 'halfling' in name as martial."),
            ("Small", "+1 size to AC and attack; +4 size to Stealth."),
        ],
    },
    {
        "id": "human", "name": "Human",
        "size": "medium", "base_speed": 30,
        "type": "humanoid (human)",
        "ability_mods": {"floating": 2},
        "starting_languages": ["common"],
        "bonus_languages_note": "Any (except secret languages such as Druidic).",
        "traits": [
            ("Bonus Feat", "Humans select one extra feat at 1st level."),
            ("Skilled", "Humans gain an additional skill rank at 1st level and one additional rank whenever they gain a level."),
        ],
    },
]


def build_race_json(r: dict) -> dict:
    mods = r["ability_mods"]
    ability_mod_list = []
    floating = mods.pop("floating", None)
    if floating is not None:
        ability_mod_list.append({"type": "floating", "value": floating,
                                 "description": f"+{floating} to one ability score of choice."})
    for ability, val in mods.items():
        ability_mod_list.append({"type": "fixed", "ability": ability, "value": val})

    return {
        "resource_id": "race",
        "stats": {
            "id": f"{r['id']}__crb_",
            "name": {"value": r["name"]},
            "source": {"value": "crb"},
            "size": {"value": r["size"]},
            "base_speed": {"value": r["base_speed"]},
            "type": {"value": r["type"]},
            "ability_score_modifiers": {"value": ability_mod_list},
            "languages_starting": {"value": r["starting_languages"]},
            "bonus_languages_note": {"value": r["bonus_languages_note"]},
            "racial_traits": {"value": [
                {"name": name, "description": desc} for (name, desc) in r["traits"]
            ]},
        },
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for r in RACES:
        data = build_race_json(r)
        path = OUT_DIR / f"race_{r['id']}__crb_.rpg.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"wrote {path.name}")
    print(f"\nDone: {len(RACES)} races")


if __name__ == "__main__":
    main()
