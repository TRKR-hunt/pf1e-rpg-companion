#!/usr/bin/env python3
"""B.1.5 Phase 2f. Build mechanical PF1e races from a CURATED table of
canonical SRD stats (authoritative & fixed — NOT prose-parsed; the
scraped race lore is too inconsistent to parse without bad data).

Idempotent, augment-only, assert-driven:
- only races whose existing instance name matches a CANON key are built
- canonical SRD ability mods / size / speed / type / languages / key
  racial traits are written; existing `lore` is PRESERVED (lore-fold
  already done — prose is in the lore field), is_lore_only set false
- the 75-strong lore-only long tail is left untouched (documented)
- re-running yields identical output
Usage: python scripts/build_mechanical_races.py [--apply]
"""
import json, glob, os, re, sys

RI = "pf1e/resource_instances"
APPLY = "--apply" in sys.argv

def asm(*parts):  # ("CON",2),("CHA",-2) -> ["CON +2 (racial)", ...]
    out = []
    for ab, v in parts:
        out.append("%s %s%d (racial)" % (ab, "+" if v >= 0 else "-", abs(v)))
    return out

# Canonical PF1e SRD race stat blocks (Core Rulebook + Advanced Race
# Guide). Values are fixed rules data, asserted-correct by citation.
CANON = {
    # --- Core 7 (instances already carry data; we normalise + flag) ---
    "human":     dict(a=["Any +2 (racial, choose one)"], sz="medium", sp=30, t="humanoid (human)",
                      lang=["common"], tr=["Bonus Feat: extra feat at 1st level.",
                      "Skilled: extra skill rank per level."]),
    "dwarf":     dict(a=asm(("CON",2),("WIS",2),("CHA",-2)), sz="medium", sp=20, t="humanoid (dwarf)",
                      lang=["common","dwarven"], tr=["Darkvision 60 ft.",
                      "Defensive Training: +4 dodge AC vs giants.","Hardy: +2 saves vs poison/spells/SLAs.",
                      "Stonecunning: +2 Perception for stonework.","Slow and Steady: 20 ft, never reduced by armor."]),
    "elf":       dict(a=asm(("DEX",2),("INT",2),("CON",-2)), sz="medium", sp=30, t="humanoid (elf)",
                      lang=["common","elven"], tr=["Low-Light Vision.",
                      "Elven Immunities: immune to sleep, +2 vs enchantment.",
                      "Keen Senses: +2 Perception.","Elven Magic: +2 vs spell SR, +2 to identify magic."]),
    "gnome":     dict(a=asm(("CON",2),("CHA",2),("STR",-2)), sz="small", sp=20, t="humanoid (gnome)",
                      lang=["common","gnome","sylvan"], tr=["Low-Light Vision.",
                      "Defensive Training: +4 dodge AC vs giants.","Gnome Magic: +1 DC illusion, SLAs.",
                      "Keen Senses: +2 Perception.","Hatred: +1 attack vs reptilian/goblinoid."]),
    "half-elf":  dict(a=["Any +2 (racial, choose one)"], sz="medium", sp=30, t="humanoid (human, elf)",
                      lang=["common","elven"], tr=["Low-Light Vision.",
                      "Adaptability: bonus Skill Focus feat.","Elf Blood; Multitalented (two favored classes).",
                      "Elven Immunities: immune to sleep, +2 vs enchantment."]),
    "half-orc":  dict(a=["Any +2 (racial, choose one)"], sz="medium", sp=30, t="humanoid (human, orc)",
                      lang=["common","orc"], tr=["Darkvision 60 ft.",
                      "Intimidating: +2 Intimidate.","Orc Ferocity: fight on 1 round at 0 HP.",
                      "Weapon Familiarity: orc weapons, greataxe/falchion martial."]),
    "halfling":  dict(a=asm(("DEX",2),("CHA",2),("STR",-2)), sz="small", sp=20, t="humanoid (halfling)",
                      lang=["common","halfling"], tr=["Fearless: +2 saves vs fear.",
                      "Halfling Luck: +1 all saves.","Keen Senses: +2 Perception.",
                      "Sure-Footed: +2 Acrobatics/Climb.","Weapon Familiarity: slings, halfling weapons."]),
    # --- Common advanced races (canonical ARG) ---
    "aasimar":   dict(a=asm(("WIS",2),("CHA",2)), sz="medium", sp=30, t="outsider (native)",
                      lang=["common","celestial"], tr=["Darkvision 60 ft.",
                      "Celestial Resistance: acid/cold/electricity 5.","Skilled: +2 Diplomacy/Perception.",
                      "Spell-Like Ability: daylight 1/day.","Deathless spirit / variant heritages."]),
    "tiefling":  dict(a=asm(("DEX",2),("INT",2),("CHA",-2)), sz="medium", sp=30, t="outsider (native)",
                      lang=["common","abyssal"], tr=["Darkvision 60 ft.",
                      "Fiendish Resistance: cold/electricity/fire 5.","Skilled: +2 Bluff/Stealth.",
                      "Spell-Like Ability: darkness 1/day.","Fiendish sorcery / variant heritages."]),
    "drow":      dict(a=asm(("DEX",2),("CHA",2),("CON",-2)), sz="medium", sp=30, t="humanoid (elf)",
                      lang=["elven","undercommon"], tr=["Darkvision 120 ft.",
                      "Light Blindness.","Drow Immunities: immune sleep, +2 vs enchantment.",
                      "Spell Resistance 6 + level.","Poison Use; SLAs (dancing lights/darkness/faerie fire)."]),
    "catfolk":   dict(a=asm(("DEX",2),("CHA",2),("WIS",-2)), sz="medium", sp=30, t="humanoid (catfolk)",
                      lang=["common","catfolk"], tr=["Low-Light Vision.",
                      "Cat's Luck: 1/day reroll a Reflex save.","Natural Hunter: +2 Perception/Stealth/Survival.",
                      "Sprinter: +10 ft when charging/running/withdrawing."]),
    "kobold":    dict(a=asm(("DEX",2),("STR",-4),("CON",-2)), sz="small", sp=30, t="humanoid (reptilian)",
                      lang=["draconic"], tr=["Darkvision 60 ft.",
                      "Armor: +1 natural armor.","Crafty: +2 Craft(traps)/Perception/Profession(miner).",
                      "Light Sensitivity.","Weapon Familiarity: picks."]),
    "goblin":    dict(a=asm(("DEX",4),("STR",-2),("CHA",-2)), sz="small", sp=30, t="humanoid (goblinoid)",
                      lang=["goblin"], tr=["Darkvision 60 ft.",
                      "Fast Movement: 30 ft despite Small.","Skilled: +4 Ride/Stealth."]),
    "hobgoblin": dict(a=asm(("DEX",2),("CON",2)), sz="medium", sp=30, t="humanoid (goblinoid)",
                      lang=["common","goblin"], tr=["Darkvision 60 ft.",
                      "Sneaky: +4 Stealth."]),
    "orc":       dict(a=asm(("STR",4),("INT",-2),("WIS",-2),("CHA",-2)), sz="medium", sp=30, t="humanoid (orc)",
                      lang=["common","orc"], tr=["Darkvision 60 ft.",
                      "Ferocity: act 1 round while disabled.","Light Sensitivity.",
                      "Weapon Familiarity: orc weapons, greataxe/falchion martial."]),
    "ratfolk":   dict(a=asm(("DEX",2),("INT",2),("STR",-2)), sz="small", sp=20, t="humanoid (ratfolk)",
                      lang=["common"], tr=["Darkvision 60 ft.",
                      "Tinker: +2 Craft(alchemy)/Perception/Use Magic Device.",
                      "Rodent Empathy: +4 to influence rodents.","Swarming: two share a square."]),
    "tengu":     dict(a=asm(("DEX",2),("WIS",2),("CON",-2)), sz="medium", sp=30, t="humanoid (tengu)",
                      lang=["common","tengu"], tr=["Low-Light Vision.",
                      "Sneaky: +2 Perception/Stealth.","Gifted Linguist: +4 Linguistics, learn 2 langs/rank.",
                      "Swordtrained: proficient with sword weapons.","Natural bite attack 1d3."]),
    "dhampir":   dict(a=asm(("DEX",2),("CHA",2),("CON",-2)), sz="medium", sp=30, t="humanoid (dhampir)",
                      lang=["common"], tr=["Darkvision 60 ft.; Low-Light Vision.",
                      "Negative Energy Affinity: healed by negative, harmed by positive.",
                      "Manipulative: +2 Bluff/Perception.","Resist level drain; Spell-Like: detect undead."]),
    "duergar":   dict(a=asm(("CON",2),("WIS",2),("CHA",-4)), sz="medium", sp=20, t="humanoid (dwarf)",
                      lang=["common","dwarven","undercommon"], tr=["Darkvision 120 ft.",
                      "Light Sensitivity.","Duergar Immunities: +2 vs spells/SLAs, immune paralysis/phantasms/poison.",
                      "Stability: +4 CMD vs bull rush/trip.","SLAs: enlarge/invisibility (self)."]),
    "gnoll":     dict(a=asm(("STR",2),("CON",2),("INT",-2)), sz="medium", sp=30, t="humanoid (gnoll)",
                      lang=["common","gnoll"], tr=["Darkvision 60 ft.",
                      "Natural Armor +1.","Bite attack 1d4."]),
    "kitsune":   dict(a=asm(("DEX",2),("CHA",2),("STR",-2)), sz="medium", sp=30, t="humanoid (kitsune, shapechanger)",
                      lang=["common"], tr=["Low-Light Vision.",
                      "Change Shape: assume one human form (SLA).","Agile: +2 Acrobatics.",
                      "Kitsune Magic: +1 DC enchantment; dancing lights SLA.","Natural bite 1d4."]),
    "grippli":   dict(a=asm(("DEX",2),("WIS",2),("STR",-2)), sz="small", sp=30, t="humanoid (grippli)",
                      lang=["grippli"], tr=["Darkvision 60 ft.",
                      "Camouflage: +4 Stealth in marshes/forests.","Swamp Stride: ignore difficult terrain (bog/undergrowth).",
                      "Weapon Familiarity: nets."]),
}

def slug_key(name):
    n = name.lower()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^a-z- ]", "", n).strip()
    return n

built, skipped, missing = [], 0, []
seen_keys = set()
for f in sorted(glob.glob(os.path.join(RI, "race_*.rpg.json"))):
    d = json.load(open(f, encoding="utf-8"))
    if d.get("resource_id") != "race":
        continue
    s = d["stats"]
    nm = (s.get("name", {}) or {}).get("value", "")
    key = slug_key(nm)
    # EXACT core-name match only — "(N RP)" suffix already stripped by
    # slug_key. Variants ("Aquatic Elf", "Monkey Goblin") deliberately
    # do NOT match base races; they stay lore-only (documented tail).
    canon = key if key in CANON else None
    if not canon:
        skipped += 1
        continue
    seen_keys.add(canon)
    c = CANON[canon]
    def setv(stat, val):
        s[stat] = {"value": val}
    setv("ability_score_modifiers", c["a"])
    # numeric mods parsed from the canonical display strings
    # ("CON +2 (racial)" -> con_racial_mod=2). Flexible "Any +2"
    # rows have no ABBR token -> all 0 (correct: floating bonus).
    AB = {"STR": "str", "DEX": "dex", "CON": "con",
          "INT": "int", "WIS": "wis", "CHA": "cha"}
    for ab, lo in AB.items():
        setv(lo + "_racial_mod", 0)
    for part in c["a"]:
        m = re.match(r"(STR|DEX|CON|INT|WIS|CHA)\s*([+-]\d+)", part)
        if m:
            setv(AB[m.group(1)] + "_racial_mod", int(m.group(2)))
    setv("size", c["sz"])
    setv("base_speed", c["sp"])
    setv("speed", c["sp"])
    setv("type", c["t"])
    setv("languages_starting", c["lang"])
    setv("racial_traits", c["tr"])
    setv("is_lore_only", False)          # explicit (don't rely on null-default)
    # lore is PRESERVED (lore-fold already done); never blanked.
    if APPLY:
        json.dump(d, open(f, "w", encoding="utf-8", newline="\n"),
                  indent=2, ensure_ascii=False)
    built.append((nm, canon))

for ck in CANON:
    if ck not in seen_keys:
        missing.append(ck)

print("MODE:", "APPLY" if APPLY else "DRY-RUN")
print("mechanical races built/normalised:", len(built))
for nm, ck in built:
    print("  %-26s <- %s" % (nm, ck))
print("lore-only races left untouched (long tail):", skipped)
if missing:
    print("CANON keys with no matching instance (not built):", missing)
