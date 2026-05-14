# Pathfinder 1e for the RPG Companion App

A community-built system pack for [RPG Companion App](https://rpg-companion.app),
modeled on the structure of the official PF2e system already in the repo.

## Status: v0.0.1 — Bootstrap complete

| Layer | Status |
|---|---|
| System metadata (`system.rpg.json`) | ✅ Rebranded as PF1e |
| Character stats DSL (`character_stats.rpgs`) | ✅ 571 lines, complete PF1e core (abilities, BAB, saves, AC, CMB/CMD, 35 skills, multiclass math, size mods, typed bonus stacking) |
| Resource type definitions (class, race, feat, spell, weapon, armor, item, archetype) | ✅ Inherited from pf2e scaffold; race renamed from ancestry; class includes PF1e-specific BAB/save progression fields |
| Character sheet sections | ⚠️ PF1e-specific sections written (saves, skills, combat stats); other inherited sections need an audit pass |
| Character creation flow | ⚠️ Skeleton inherited from pf2e; needs PF1e-specific pages (race → class → ability scores → skills → feats → equipment → details) |
| Enumerated types (alignment, size, school, etc.) | ⚠️ Inherited; needs PF1e values |
| **Content: 11 Core classes** | ✅ Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Sorcerer, Wizard |
| **Content: 7 Core races** | ✅ Dwarf, Elf, Gnome, Half-Elf, Half-Orc, Halfling, Human |
| **Content: 31 essential Core feats** | ✅ Includes the canonical mechanically-modeled ones (Power Attack, Combat Expertise, Dodge, Toughness, Iron Will, ...) |
| **Content: 31 essential Core spells** | ✅ Cantrips through 3rd level across all Core casters |
| **Content: 66 weapons + 18 armors/shields** | ✅ Complete CRB simple/martial/exotic weapons and all armors |
| Scrapers (`scripts/scrape_feats.py`, `scrape_spells.py`) | ✅ Ready to run on a machine with network access; polite (2-sec rate limit), cached, respects UA. Will produce the long tail of ~400 more feats and ~400 more spells. |
| Validator (`scripts/validate_resource_instances.py`) | ✅ All 164 instances pass |

Total resource instances: **164 validated files**.

## Repository layout

```
systems/pf1e/
  system/
    system.rpg.json              # System metadata (id, name, version, etc.)
    character_stats.rpgs         # Core stat DSL: abilities, saves, AC, BAB, 35 skills, etc.
    character_search_item_view.rpgs
    character_sheet_sections/    # UI for the character sheet
    character_creation_flow/     # Step-by-step character creation pages
    combat_system/               # Initiative + combat tracking config
    enumerated_types/            # Alignments, sizes, schools, damage types
    macros/                      # System-local DSL macros
    mechanics/                   # System-level mechanics
    resources/                   # Resource type definitions (class, race, feat, ...)
  resource_instances/            # Flat directory of content (the 164 files)

scripts/
  build_core_classes.py          # Regenerates the 11 Core class files
  build_core_races.py            # Regenerates the 7 Core race files
  build_core_weapons.py          # Regenerates 66 weapons
  build_core_armor.py            # Regenerates 18 armors/shields
  build_core_feats.py            # Regenerates 31 essential feats
  build_core_spells.py           # Regenerates 31 essential spells
  scrape_feats.py                # Fetches more feats from d20pfsrd
  scrape_spells.py               # Fetches more spells from d20pfsrd
  validate_resource_instances.py # Schema validator
```

## Where the work goes from here

### Phase A — Finish the system shell (~1 day)
1. Audit and update inherited sheet sections (`05b_resources`, `09_companions`, `10_features`, `11_armors`, `12_weapons`, `13_equipment`, `16_spells`) for PF1e idioms.
2. Replace `character_creation_flow/` with a PF1e flow:
   1. Race
   2. Class (with multi-class support hook)
   3. Ability scores (15-point buy default; selectable to roll/elite array)
   4. Skill ranks (with class-skill highlighting)
   5. Feats (1 + bonus from class/race)
   6. Equipment (with starting wealth roll)
   7. Spells (for casters)
   8. Background details
3. Fill in `enumerated_types/` with PF1e values:
   - Alignments: LG, NG, CG, LN, TN, CN, LE, NE, CE
   - Sizes: Fine through Colossal
   - Spell schools: Abjuration, Conjuration, Divination, Enchantment, Evocation, Illusion, Necromancy, Transmutation, Universal
   - Damage types: bludgeoning, piercing, slashing, acid, cold, electricity, fire, sonic, force, negative, positive
   - Save types: Fortitude, Reflex, Will

### Phase B — Bulk content via scrapers (~1 day of running, then several days of QA)
1. Run scrapers (need network access to d20pfsrd.com):
   ```
   pip install requests beautifulsoup4
   cd scripts
   python scrape_feats.py --category combat
   python scrape_feats.py --category general
   python scrape_feats.py --category metamagic
   python scrape_feats.py --category item-creation
   python scrape_spells.py --list sorcerer-wizard --max-level 9
   python scrape_spells.py --list cleric --max-level 9
   python scrape_spells.py --list druid --max-level 9
   python scrape_spells.py --list bard --max-level 6
   python scrape_spells.py --list paladin --max-level 4
   python scrape_spells.py --list ranger --max-level 4
   ```
   Expected output: ~400 feats and ~400 spells in `resource_instances/`. Scraping runs at 1 page per 2 seconds (politely); the full pull takes around 1-2 hours of wall time but most of that is the cache warming up. Subsequent runs are free.
2. AI-assisted pass: for each scraped feat/spell, refine its `effects` array. Most scraped feats land in `resource_instances/` with `effects: []` and a verbatim description; the next pass turns the prose into structured typed effects (this is the work that Claude Code/Cowork is well-suited for).
3. Validate after every batch: `python scripts/validate_resource_instances.py`.

### Phase C — Test in the app
1. Use the RPG Companion App dev tool (per the docs) to load the system locally.
2. Try creating one character of each class to surface stat-formula and UI bugs.
3. Tag v0.1.0, publish via the in-app GitHub wizard.

### Phase D — Long tail (post-v0.1)
- Archetypes (huge category, ship as v0.2)
- Hybrid/Alternate/Unchained classes
- Prestige classes
- Magic items
- Bestiary
- Traits (PF1e-specific 1-pick character traits)

## Conventions

- Filenames: `{resource_id}_{slug}__{source}_.rpg.json` (e.g. `class_fighter__crb_`, `spell_fireball__crb_`).
- The `id` field inside `stats` is a raw string (NOT wrapped in `{value: ...}`).
- For feats specifically, the `id` already includes the `feat_` prefix; for all other resource types it does not. (This matches the pf2e convention.)
- Every other field is wrapped in `{"value": ...}`.
- Source codes used:
  - `crb` = Core Rulebook (Pathfinder 1e)
  - Add more as you expand: `apg` (Advanced Player's Guide), `um` (Ultimate Magic), `uc` (Ultimate Combat), `arg` (Advanced Race Guide), etc.

## Licensing

- Content licensed under CC BY-NC-SA 4.0 (matching the parent rpg-companion-app-systems repo).
- Pathfinder 1e content sourced from d20pfsrd.com, which itself publishes under the Open Game License (OGL 1.0a). Make sure to include the OGL section 15 attributions in any v1.0 publication.
- Scripts and tooling MIT.
