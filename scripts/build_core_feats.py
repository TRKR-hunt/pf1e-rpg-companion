#!/usr/bin/env python3
"""Build a curated set of essential Core Rulebook feats.

These cover the feats most likely to appear on starting characters and
demonstrate how to encode each kind of mechanical effect:
  - Flat stat bonuses (Toughness, Iron Will)
  - Conditional toggleable effects (Power Attack, Combat Expertise)
  - Combat maneuver chains (Improved Trip, Improved Disarm)
  - Skill bonuses (Skill Focus, Alertness)
  - Action economy modifiers (Combat Reflexes, Quick Draw)

When scrape_feats.py runs later, it will fill in the long tail.
"""
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"


def feat(id_, name, type_, prereqs, description, effects=None, is_toggleable=False):
    return {
        "resource_id": "feat",
        "stats": {
            "id": f"feat_{id_}__crb_",
            "name": {"value": name},
            "source": {"value": "crb"},
            "type": {"value": type_},
            "traits": {"value": type_},
            "prerequisites": {"value": prereqs},
            "description": {"value": description},
            "is_toggleable": {"value": is_toggleable},
            "effects": {"value": effects or []},
            "action_cost": {"value": "passive"},
        },
    }


def effect_typed(eid, name, stat, value, mod_type="untyped", polarity="bonus",
                 trigger="passive"):
    return {
        "resource_id": "effect",
        "stats": {
            "id": eid,
            "name": {"value": name},
            "trigger_type": {"value": trigger},
            "type": {"value": "typed_add_to_stat"},
            "typed_modifier_type": {"value": mod_type},
            "typed_modifier_polarity": {"value": polarity},
            "stat": {"value": stat},
            "constant": {"value": value},
        },
    }


# Compact list. Each tuple: (id, name, category, prereqs, desc, effects)
FEATS = [
    # GENERAL — combat-adjacent
    ("alertness", "Alertness", "general", "",
     "+2 on Perception and Sense Motive (+4 with 10 ranks in each).",
     [effect_typed("eff_alertness_perception", "+2 Perception", "$character.perception", 2),
      effect_typed("eff_alertness_sensemotive", "+2 Sense Motive", "$character.sense_motive", 2)]),

    ("toughness", "Toughness", "general", "",
     "Gain +3 HP, plus +1 HP per HD beyond 3rd. HP bonus is permanent.",
     [effect_typed("eff_toughness", "+HP from Toughness", "$character.hp_misc", 3,
                   mod_type="untyped",
                   trigger="passive")]),

    ("iron_will", "Iron Will", "general", "",
     "+2 bonus on all Will saving throws.",
     [effect_typed("eff_iron_will", "+2 Will", "$character.will_misc", 2)]),

    ("lightning_reflexes", "Lightning Reflexes", "general", "",
     "+2 bonus on all Reflex saving throws.",
     [effect_typed("eff_lightning_reflexes", "+2 Reflex", "$character.reflex_misc", 2)]),

    ("great_fortitude", "Great Fortitude", "general", "",
     "+2 bonus on all Fortitude saving throws.",
     [effect_typed("eff_great_fortitude", "+2 Fort", "$character.fortitude_misc", 2)]),

    ("skill_focus", "Skill Focus", "general", "",
     "Choose a skill. +3 bonus to that skill; increases to +6 once you have 10 ranks. (Repeatable.)",
     []),

    ("run", "Run", "general", "",
     "Run x5 (instead of x4); retain Dex bonus to AC; +4 bonus on Acrobatic checks made to jump.",
     []),

    ("endurance", "Endurance", "general", "",
     "+4 bonus on Swim, Constitution, and similar checks to resist environmental fatigue.",
     []),

    ("diehard", "Diehard", "general", "Endurance",
     "When between 0 and -CON HP, you act normally; you only die at -CON-1 HP.",
     []),

    # COMBAT FEATS
    ("power_attack", "Power Attack", "combat", "Str 13, base attack bonus +1",
     "Trade –1 melee atk for +2 melee damage (×1.5 if two-handed, ×0.5 if off-hand). Penalty/bonus scale with BAB.",
     [
       effect_typed("eff_pa_atk", "Power Attack: melee atk", "$character.melee_attack_bonus", -1,
                    polarity="penalty", trigger="toggleable"),
       effect_typed("eff_pa_dmg", "Power Attack: melee dmg", "$character.melee_damage_bonus", 2,
                    trigger="toggleable"),
     ]),

    ("cleave", "Cleave", "combat", "Str 13, Power Attack, base attack bonus +1",
     "As a standard action, attack one foe; if you hit, you may make a second attack at the same bonus against an adjacent foe. Take –2 AC until your next turn.",
     []),

    ("combat_expertise", "Combat Expertise", "combat", "Int 13",
     "Take –1 atk for +1 dodge bonus to AC. Penalty and bonus increase by 1 every 4 BAB.",
     [
       effect_typed("eff_ce_atk", "Combat Expertise: atk", "$character.melee_attack_bonus", -1,
                    polarity="penalty", trigger="toggleable"),
       effect_typed("eff_ce_ac",  "Combat Expertise: AC",  "$character.dodge_bonus", 1,
                    mod_type="dodge", trigger="toggleable"),
     ]),

    ("dodge", "Dodge", "combat", "Dex 13",
     "+1 dodge bonus to AC.",
     [effect_typed("eff_dodge", "Dodge +1 AC", "$character.dodge_bonus", 1, mod_type="dodge")]),

    ("mobility", "Mobility", "combat", "Dex 13, Dodge",
     "+4 dodge bonus to AC against attacks of opportunity provoked by movement.",
     []),

    ("spring_attack", "Spring Attack", "combat", "Dex 13, Dodge, Mobility, base attack bonus +4",
     "When using attack action with melee weapon, move both before and after; total distance no more than speed; no AoO from target.",
     []),

    ("weapon_focus", "Weapon Focus", "combat", "Proficiency with chosen weapon, base attack bonus +1",
     "+1 bonus on attack rolls with chosen weapon. (Repeatable; choose different weapon each time.)",
     []),

    ("weapon_specialization", "Weapon Specialization", "combat",
     "Proficiency with chosen weapon, Weapon Focus with weapon, fighter level 4th",
     "+2 bonus on damage rolls with chosen weapon.",
     []),

    ("improved_initiative", "Improved Initiative", "combat", "",
     "+4 bonus on initiative checks.",
     [effect_typed("eff_imp_init", "+4 Initiative", "$character.initiative_misc", 4)]),

    ("combat_reflexes", "Combat Reflexes", "combat", "",
     "May make AoOs equal to 1 + Dex modifier per round; can make AoOs while flat-footed.",
     []),

    ("point_blank_shot", "Point-Blank Shot", "combat", "",
     "+1 atk and +1 dmg with ranged weapons against targets within 30 ft.",
     []),

    ("precise_shot", "Precise Shot", "combat", "Point-Blank Shot",
     "No –4 penalty for shooting into melee.",
     []),

    ("rapid_shot", "Rapid Shot", "combat", "Dex 13, Point-Blank Shot",
     "When making full-attack with ranged weapon, gain one extra attack at highest BAB; all attacks take –2.",
     []),

    ("manyshot", "Manyshot", "combat", "Dex 17, Point-Blank Shot, Rapid Shot, base attack bonus +6",
     "When making first ranged attack on full-attack with bow, fire two arrows. Both deal damage if it hits; only first applies precision/extra dice.",
     []),

    ("improved_unarmed_strike", "Improved Unarmed Strike", "combat", "",
     "Unarmed strikes are treated as armed; no AoO when striking unarmed.",
     []),

    ("improved_grapple", "Improved Grapple", "combat", "Dex 13, Improved Unarmed Strike",
     "+2 on grapple checks; do not provoke AoO when attempting to grapple.",
     []),

    ("improved_disarm", "Improved Disarm", "combat", "Int 13, Combat Expertise",
     "+2 on disarm; no AoO when disarming.",
     []),

    ("improved_trip", "Improved Trip", "combat", "Int 13, Combat Expertise",
     "+2 on trip; no AoO when tripping; if you trip, you get an immediate attack.",
     []),

    ("two_weapon_fighting", "Two-Weapon Fighting", "combat", "Dex 15",
     "Reduce two-weapon penalties: –4/–4 becomes –2/–2 (or –4/–4 if off-hand is non-light).",
     []),

    ("improved_two_weapon_fighting", "Improved Two-Weapon Fighting", "combat",
     "Dex 17, Two-Weapon Fighting, base attack bonus +6",
     "Gain a second off-hand attack at –5 to the second.",
     []),

    ("quick_draw", "Quick Draw", "combat", "base attack bonus +1",
     "Draw a weapon as a free action.",
     []),

    ("vital_strike", "Vital Strike", "combat", "base attack bonus +6",
     "As a standard action, make one attack that rolls weapon damage dice an additional time.",
     []),
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for tup in FEATS:
        # Tuple may have 5 or 6 elements - last optional is is_toggleable inside feat() helper
        if len(tup) == 5:
            id_, name, cat, pre, desc = tup
            effects = []
        else:
            id_, name, cat, pre, desc, effects = tup
        # Detect toggleable from id heuristic
        toggleable = id_ in {"power_attack", "combat_expertise"}
        data = feat(id_, name, cat, pre, desc, effects=effects, is_toggleable=toggleable)
        path = OUT_DIR / f"feat_{id_}__crb_.rpg.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Done: {len(FEATS)} feats")


if __name__ == "__main__":
    main()
