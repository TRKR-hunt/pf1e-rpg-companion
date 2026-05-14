# Pathfinder 1e for RPG Companion App — Build Plan

## Target for v0.1.0 (Core Rulebook MVP)
Modeled on pf2e's release scope:
- 11 Core classes (Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Sorcerer, Wizard)
- 7 Core races (Dwarf, Elf, Gnome, Half-Elf, Half-Orc, Halfling, Human)
- ~400 Combat + General feats from Core Rulebook
- ~400 spells (levels 0–6 across all Core lists)
- Core weapons, armor, basic adventuring gear
- Full character sheet with PF1e stat block

## Architecture (modeled on pf2e in the repo)
```
systems/pf1e/
  system/
    system.rpg.json              # Top-level system definition
    character_stats.rpgs         # All character stats with formulas
    character_search_item_view.rpgs
    character_sheet_sections/    # One .rpgs per sheet section
    character_creation_flow/     # Step-by-step creation pages
    enumerated_types/            # Alignments, sizes, schools, etc.
    macros/
    mechanics/
    resources/                   # Resource type definitions
      class/
      race/                      # PF1e calls this race, not ancestry
      feat/
      spell/
      weapon/
      armor/
      item/
      trait/
      archetype/
      ...
    combat_system/
  resource_instances/            # ~1500 flat JSON files
    class_fighter__crb_.rpg.json
    feat_power_attack__crb_.rpg.json
    spell_fireball__crb_.rpg.json
    ...
```

## PF1e-specific stat block

Character stats we need to model:
- 6 ability scores + modifiers (formula: floor((score-10)/2))
- BAB (per-class table, sums across classes)
- 3 saves (Fort/Ref/Will, per-class table + ability mod)
- AC (10 + armor + shield + Dex (capped by armor) + size + dodge + natural + deflection + misc)
- Touch AC, Flat-Footed AC
- CMB (BAB + Str + size mod)
- CMD (10 + BAB + Str + Dex + size + misc)
- HP (sum of class HD + Con mod × level + favored class bonus)
- Initiative (Dex + misc)
- Speed (race base, modified by armor)
- 35 skills (rank + ability mod + class skill bonus +3 if trained + misc)
- Spells per day (per class table, +bonus from high ability score)

## Key PF1e mechanics that need formula support
- Typed bonus stacking (enhancement, morale, sacred, profane, dodge stack with self, etc.)
- BAB → iterative attacks (+6/+1 at BAB 6, +11/+6/+1 at BAB 11, etc.)
- Multiclass math (sum BAB rounded, saves: best save category by class)
- Size modifiers (Tiny/Small/Med/Large each affects AC, attack, CMB, CMD, Stealth)
- Skill ranks: max ranks per level = character level; class skill = +3 if any rank

## Phases

### Phase 1: System skeleton (4-6 hours)
- [ ] Create directory structure
- [ ] Write system.rpg.json with PF1e metadata
- [ ] Define character_stats.rpgs (all derived stats with formulas)
- [ ] Define character_sheet_sections
- [ ] Define character_creation_flow (7 pages: race, class, abilities, skills, feats, equipment, details)
- [ ] Define enumerated_types (alignment, size, school, damage_type, etc.)
- [ ] Define progression system (XP-based, with slow/medium/fast)

### Phase 2: Resource type definitions (2-4 hours)
For each resource type, define stats schema + display_view + edit_view + search_item_view:
- [ ] class
- [ ] race
- [ ] feat
- [ ] spell
- [ ] weapon, armor, item
- [ ] trait (PF1e-specific, replaces pf2e backgrounds partially)
- [ ] archetype

### Phase 3: Content scraping & generation (the bulk of work)
- [ ] Build polite scraper for d20pfsrd (respect robots.txt, rate-limit)
- [ ] Scrape: 11 Core classes
- [ ] Scrape: 7 Core races
- [ ] Scrape: Combat + General feats (~400)
- [ ] Scrape: Spells (~400, level 0-6, Core)
- [ ] Scrape: Core weapons (~60)
- [ ] Scrape: Core armor (~20)
- [ ] AI-assisted JSON conversion (batched, 20 at a time, with validation)

### Phase 4: Validation & polish
- [ ] Run scripts/validate_resource_instances.py
- [ ] Fix schema errors
- [ ] Test in app dev tool
- [ ] Tag v0.1.0

## Notes on differences from PF2e schema
- PF1e action types: standard / move / swift / immediate / free / full-round (not the 3-action economy)
- PF1e spells have "school" prominently (Pf2e has it but de-emphasized)
- PF1e has "trait" (1- or 2-pick character traits at creation)
- PF1e classes have BAB progression (full/three-quarter/half) — must model
- PF1e classes have save progression (good = 2 + level/2; poor = level/3)
- PF1e has spell components V/S/M/F/DF; pf2e simplified these
- PF1e doesn't have "proficiency tiers" (trained/expert/master) — it's BAB or skill ranks
