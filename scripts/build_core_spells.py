#!/usr/bin/env python3
"""Build a curated set of essential Core Rulebook spells.

These cover canonical low-level spells most likely to appear on starting
characters across the Core spellcasting classes. When scrape_spells.py runs
later, it fills in the long tail.

Format: (id, name, level, school, classes, casting_time, components, range,
         target_or_area, duration, save, sr, description)
"""
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

SPELLS = [
    # CANTRIPS / ORISONS
    ("light", "Light", 0, "evocation", ["sorcerer", "wizard", "bard", "cleric"],
     "1 standard action", "V, M/DF", "touch", "object touched", "10 min/level", "none", "no",
     "Object touched shines like a torch (20-foot radius normal light, dim light to 40 ft)."),
    ("detect_magic", "Detect Magic", 0, "divination", ["sorcerer", "wizard", "bard", "cleric", "druid"],
     "1 standard action", "V, S", "60 ft", "cone-shaped emanation", "concentration, up to 1 min/level", "none", "no",
     "Detect magical auras, learn strength and school over up to 3 rounds of concentration."),
    ("read_magic", "Read Magic", 0, "divination", ["sorcerer", "wizard", "bard", "cleric", "druid", "paladin", "ranger"],
     "1 standard action", "V, S, F", "personal", "you", "10 min/level", "none", "no",
     "Read scrolls and spellbooks; identify glyphs and runes."),
    ("mage_hand", "Mage Hand", 0, "transmutation", ["sorcerer", "wizard", "bard"],
     "1 standard action", "V, S", "close (25 ft + 5 ft/2 levels)", "one nonmagical, unattended object up to 5 lb.",
     "concentration", "none", "no",
     "Move target up to 15 ft per round; cannot lift higher than your reach."),
    ("acid_splash", "Acid Splash", 0, "conjuration (creation) [acid]", ["sorcerer", "wizard"],
     "1 standard action", "V, S", "close (25 ft + 5 ft/2 levels)", "one orb of acid",
     "instantaneous", "none", "no",
     "Ranged touch attack; 1d3 acid damage."),

    # 1ST LEVEL
    ("magic_missile", "Magic Missile", 1, "evocation [force]", ["sorcerer", "wizard"],
     "1 standard action", "V, S", "medium (100 ft + 10 ft/level)", "up to 5 creatures, no two more than 15 ft apart",
     "instantaneous", "none", "yes",
     "A force missile that hits unerringly for 1d4+1 damage. +1 missile per 2 caster levels above 1st, to a max of 5 missiles at 9th level."),
    ("mage_armor", "Mage Armor", 1, "conjuration (creation) [force]", ["sorcerer", "wizard"],
     "1 standard action", "V, S, F", "touch", "creature touched", "1 hour/level (D)", "Will negates (harmless)", "no",
     "+4 armor bonus to AC."),
    ("shield", "Shield", 1, "abjuration [force]", ["sorcerer", "wizard"],
     "1 standard action", "V, S", "personal", "you", "1 min/level (D)", "none", "no",
     "+4 shield bonus to AC; negates magic missile."),
    ("burning_hands", "Burning Hands", 1, "evocation [fire]", ["sorcerer", "wizard"],
     "1 standard action", "V, S", "15 ft", "cone-shaped burst", "instantaneous", "Reflex half", "yes",
     "1d4 fire damage per caster level (max 5d4)."),
    ("sleep", "Sleep", 1, "enchantment (compulsion) [mind-affecting]", ["sorcerer", "wizard", "bard"],
     "1 round", "V, S, M", "medium (100 ft + 10 ft/level)", "one or more living creatures within a 10-ft-radius burst",
     "1 min/level", "Will negates", "yes",
     "Puts 4 HD of creatures into magical slumber. Creatures with 5+ HD unaffected."),
    ("charm_person", "Charm Person", 1, "enchantment (charm) [mind-affecting]", ["sorcerer", "wizard", "bard"],
     "1 standard action", "V, S", "close (25 ft + 5 ft/2 levels)", "one humanoid creature", "1 hour/level",
     "Will negates", "yes",
     "Target regards you as a trusted friend and ally."),
    ("cure_light_wounds", "Cure Light Wounds", 1, "conjuration (healing)",
     ["cleric", "druid", "bard", "paladin", "ranger"],
     "1 standard action", "V, S", "touch", "creature touched", "instantaneous", "Will half (harmless); see text", "yes",
     "Cures 1d8 + caster level (max +5) HP."),
    ("bless", "Bless", 1, "enchantment (compulsion) [mind-affecting]", ["cleric", "paladin"],
     "1 standard action", "V, S, DF", "50 ft", "you and all allies within 50 ft", "1 min/level", "none", "yes (harmless)",
     "+1 morale bonus on attack rolls and on saves vs fear."),
    ("divine_favor", "Divine Favor", 1, "evocation", ["cleric", "paladin"],
     "1 standard action", "V, S, DF", "personal", "you", "1 minute", "none", "no",
     "+1 luck bonus on attack and weapon damage rolls per 3 caster levels (max +3)."),
    ("entangle", "Entangle", 1, "transmutation", ["druid", "ranger"],
     "1 standard action", "V, S, DF", "long (400 ft + 40 ft/level)", "plants in 40-ft-radius spread",
     "1 min/level (D)", "Reflex partial; see text", "no",
     "Plants entangle creatures within area."),
    ("obscuring_mist", "Obscuring Mist", 1, "conjuration (creation)",
     ["sorcerer", "wizard", "cleric", "druid"],
     "1 standard action", "V, S", "20 ft", "cloud spreads in 20-ft radius from you, 20 ft high", "1 min/level", "none", "no",
     "Concealment in mist; total concealment beyond 5 ft."),
    ("expeditious_retreat", "Expeditious Retreat", 1, "transmutation", ["sorcerer", "wizard", "bard"],
     "1 standard action", "V, S", "personal", "you", "1 min/level (D)", "none", "no",
     "Land speed increases by 30 ft (enhancement bonus)."),

    # 2ND LEVEL
    ("invisibility", "Invisibility", 2, "illusion (glamer)", ["sorcerer", "wizard", "bard"],
     "1 standard action", "V, S, M/DF", "personal or touch", "you or creature/object up to 100 lb./level",
     "1 min/level (D)", "Will negates (harmless)", "yes (harmless)",
     "Target becomes invisible. Attacking breaks the spell."),
    ("scorching_ray", "Scorching Ray", 2, "evocation [fire]", ["sorcerer", "wizard"],
     "1 standard action", "V, S", "close (25 ft + 5 ft/2 levels)", "one or more rays", "instantaneous",
     "none", "yes",
     "4d6 fire damage per ray. One ray at 1st, +1 ray every 4 caster levels (max 3 at 11th)."),
    ("mirror_image", "Mirror Image", 2, "illusion (figment)", ["sorcerer", "wizard", "bard"],
     "1 standard action", "V, S", "personal", "you", "1 min/level (D)", "none", "no",
     "1d4 + 1 per 3 levels (max 8) duplicates appear; attacks may hit a duplicate."),
    ("acid_arrow", "Acid Arrow", 2, "conjuration (creation) [acid]", ["sorcerer", "wizard"],
     "1 standard action", "V, S, F, M", "long (400 ft + 40 ft/level)", "one arrow of acid", "1 round + 1/3 levels",
     "none", "no",
     "Ranged touch; 2d4 acid damage immediately and on subsequent rounds."),
    ("hold_person", "Hold Person", 2, "enchantment (compulsion) [mind-affecting]",
     ["sorcerer", "wizard", "bard", "cleric"],
     "1 standard action", "V, S, F/DF", "medium (100 ft + 10 ft/level)", "one humanoid creature",
     "1 round/level (D); see text", "Will negates; see text", "yes",
     "Target paralyzed. New save each round."),
    ("bull_strength", "Bull's Strength", 2, "transmutation", ["sorcerer", "wizard", "cleric", "paladin"],
     "1 standard action", "V, S, M/DF", "touch", "creature touched", "1 min/level", "Will negates (harmless)", "yes (harmless)",
     "+4 enhancement bonus to Strength."),
    ("cat_grace", "Cat's Grace", 2, "transmutation", ["sorcerer", "wizard", "bard", "druid", "ranger"],
     "1 standard action", "V, S, M", "touch", "creature touched", "1 min/level", "Will negates (harmless)", "yes (harmless)",
     "+4 enhancement bonus to Dexterity."),
    ("bear_endurance", "Bear's Endurance", 2, "transmutation", ["sorcerer", "wizard", "cleric", "druid", "ranger"],
     "1 standard action", "V, S, M/DF", "touch", "creature touched", "1 min/level", "Will negates (harmless)", "yes (harmless)",
     "+4 enhancement bonus to Constitution."),
    ("spiritual_weapon", "Spiritual Weapon", 2, "evocation [force]", ["cleric"],
     "1 standard action", "V, S, DF", "medium (100 ft + 10 ft/level)", "magical weapon of force", "1 round/level",
     "none", "yes",
     "Force weapon attacks target you direct; uses your BAB; deals 1d8 + 1 per 3 caster levels (max +5) damage."),

    # 3RD LEVEL
    ("fireball", "Fireball", 3, "evocation [fire]", ["sorcerer", "wizard"],
     "1 standard action", "V, S, M", "long (400 ft + 40 ft/level)", "20-ft-radius spread", "instantaneous",
     "Reflex half", "yes",
     "1d6 fire damage per caster level (max 10d6)."),
    ("lightning_bolt", "Lightning Bolt", 3, "evocation [electricity]", ["sorcerer", "wizard"],
     "1 standard action", "V, S, M", "120 ft", "120-ft line", "instantaneous", "Reflex half", "yes",
     "1d6 electricity damage per caster level (max 10d6) in a line."),
    ("haste", "Haste", 3, "transmutation", ["sorcerer", "wizard", "bard"],
     "1 standard action", "V, S, M", "close (25 ft + 5 ft/2 levels)", "one creature/level, no two more than 30 ft apart",
     "1 round/level", "Fortitude negates (harmless)", "yes (harmless)",
     "Targets get +1 attack on full-attack, +1 dodge AC, +1 Reflex, +30 ft speed."),
    ("fly", "Fly", 3, "transmutation", ["sorcerer", "wizard"],
     "1 standard action", "V, S, F", "touch", "creature touched", "1 min/level", "Will negates (harmless)", "yes (harmless)",
     "Fly speed 60 ft (40 in medium/heavy armor or carrying medium/heavy load)."),
    ("dispel_magic", "Dispel Magic", 3, "abjuration",
     ["sorcerer", "wizard", "cleric", "druid", "bard", "paladin"],
     "1 standard action", "V, S", "medium (100 ft + 10 ft/level)", "one spellcaster, creature, or object",
     "instantaneous", "none", "no",
     "End ongoing spells on target. d20 + caster level vs DC 11 + opposing caster level per spell."),
]


def _normalize_school(s: str) -> str:
    # Strip pf2e/PF1e subschool & descriptor metadata like
    # "conjuration (creation) [acid]" -> "conjuration", so the value is a
    # valid id in the spell_school enum.
    return s.split("(", 1)[0].split("[", 1)[0].strip().lower()


def build_spell_json(t):
    (id_, name, lvl, school, classes, ct, comps, rng, area, dur, save, sr, desc) = t
    return {
        "resource_id": "spell",
        "stats": {
            "id": f"{id_}__crb_",
            "name": {"value": name},
            "source": {"value": "crb"},
            "level": {"value": f"spell_level_{lvl}"},
            "school": {"value": _normalize_school(school)},
            "classes": {"value": classes},
            "casting_time": {"value": ct},
            "components": {"value": comps},
            "range": {"value": rng},
            "area": {"value": area},
            "duration": {"value": dur},
            "saving_throw": {"value": save},
            "spell_resistance": {"value": sr},
            "description": {"value": desc},
        },
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for s in SPELLS:
        data = build_spell_json(s)
        path = OUT_DIR / f"spell_{s[0]}__crb_.rpg.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Done: {len(SPELLS)} spells")


if __name__ == "__main__":
    main()
