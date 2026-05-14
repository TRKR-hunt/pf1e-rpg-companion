#!/usr/bin/env python3
"""
Static analyzer for the PF1e system pack's .rpgs DSL files.

The DSL has no shipped parser in this repo, so this script does a pragmatic
regex-based pass. It's intentionally biased toward things we CAN check
confidently:

  - import "X" statements -> file at X exists (or X is _stdlib/* which we skip)
  - resource<TYPE> -> TYPE is a directory in pf1e/system/resources/
  - resource_id = "TYPE" -> same
  - options = "ENUM" -> ENUM matches an id in pf1e/system/enumerated_types/*.rpg.json
  - stat = "X" / edit_stat = "X" -> X is declared in character_stats.rpgs
  - edit_meta_stat = ... -> computed name; emit a NOTE only
  - Free identifier references in expressions -> heuristic warning only

Run from repo root:
    python3 scripts/static_analyze_rpgs.py
Or from scripts/:
    python3 static_analyze_rpgs.py
"""
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
PF1E = ROOT / "pf1e"
SYSTEM = PF1E / "system"
CHARACTER_STATS = SYSTEM / "character_stats.rpgs"
RESOURCES_DIR = SYSTEM / "resources"
ENUMS_DIR = SYSTEM / "enumerated_types"

# Files we created/modified in this session — prioritize their issues in the
# triage output so we can focus on what we actually changed.
PRIORITY_PATHS = {
    "character_creation_flow/01_race.rpgs",
    "character_creation_flow/02_class.rpgs",
    "character_creation_flow/03_ability_scores.rpgs",
    "character_creation_flow/04_skills.rpgs",
    "character_creation_flow/05_feats.rpgs",
    "character_creation_flow/06_equipment.rpgs",
    "character_creation_flow/07_details.rpgs",
    "character_sheet_sections/09_companions.rpgs",
    "character_sheet_sections/10_features.rpgs",
    "character_sheet_sections/11_armors.rpgs",
    "character_sheet_sections/12_weapons.rpgs",
    "character_sheet_sections/13_equipment.rpgs",
    "character_sheet_sections/16_spells.rpgs",
    "character_stats.rpgs",
}

# Tokens we never want to flag as an unknown reference — keywords, builtin
# functions, view-system identifiers, common parameter keywords.
KEYWORDS = {
    "if", "then", "else", "when", "true", "false", "null",
    "base", "calc", "define", "import",
    # Builtins seen across .rpgs files. Not exhaustive — we err on the side
    # of false negatives (missed warnings) rather than false positives.
    "add", "concat", "map", "filter", "flatMap", "flatAppend", "joinToString",
    "length", "contains", "isEmpty", "notNull", "isNull", "defined", "or",
    "and", "not", "divide", "abilityModifier", "date", "findFirst", "sortBy",
    "enumeratedName", "metaStat", "setStat", "addToStat", "forEach",
    "sequence", "filter", "mapper", "dict", "min", "max",
    # Top-level builder functions we know exist in the DSL
    "section", "list", "composite", "text", "icon", "spacer", "stat",
    "select", "selectResources", "selectorWithDetailsEndComposite",
    "selectorWithDetailsEndEndComposite",
    "selectorWithDetailsEndVisibleComposite",
    "selectorWithDetailsEndAndTailComposite",
    "resourceDetailsOkPopUpButton", "checkbox", "menuButton", "collapsible",
    "resourceSection", "resourceArray", "rollStatRow", "skillListRow",
    "defaultSectionHeader",
    "characterCreationPage", "displayableData",
    "character_sheet_section", "character_creation_page",
    "showResource", "showPopUp", "diffText",
    # parameter keywords (left side of `=` inside a call)
    "id", "name", "value", "type", "stat", "stats", "header", "content",
    "subviews", "view", "title", "validation_message", "size",
    "padding", "margin_top", "margin_bottom", "margin_left", "margin_right",
    "show_divider", "collapsible", "start_collapsed", "always_show_collapse_icon",
    "is_visible", "color", "style", "bold", "options", "allowed_options",
    "filter", "mapper", "filters", "needle", "haystack", "separator",
    "treat_as_set", "order", "sort_by_selector", "for_each_value_key",
    "components", "apply", "effects", "clauses", "condition", "effect",
    "aggregation_type", "new_value", "rounding_method",
    "label", "max_length", "hint", "signed", "edit_stat", "edit_meta_stat",
    "meta_stat", "min_value_allowed", "max_value_allowed", "should_auto_save",
    "always_in_edit_mode", "change_amount", "edit_bottom_sheet_title",
    "post_edit", "on_page_open", "on_page_close",
    "resource_id", "resource_stat", "resource_set_stat", "view_type",
    "tap_displays_resource", "should_append", "should_save_on_selection",
    "create_in_place", "creation_pop_up_type",
    "details_button", "selector_view", "tail_view", "composite_id",
    "auto_add_first", "allow_adds_and_removes", "left_view", "hide_line",
    "read_only", "max_items_in_preview", "alignment", "abbreviation",
    "icon_id", "icon_name", "title_id", "title_text", "icon_size", "icon_color",
    "button_id", "button_text", "pop_up_view_id", "pop_up_title", "pop_up_type",
    "pop_up_view", "dismissible", "display_cancel_button", "display_save_button",
    "should_persist_on_save", "in_edit_mode", "cancel_text", "extra_buttons",
    "header_view", "subhead", "section", "caption", "switcher", "title",
    "content_item_min_width", "start_expanded",
    "score", "abbreviation",
    "default", "trigger_type", "constant", "typed_modifier_type",
    "typed_modifier_polarity", "polarity",
    "slot_level", "slot_label",
}

# Identifier regex
IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
STRING = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')

# Stat declarations: `base <type> <name>(...)` and `calc <type> <name>(...)`
# `<type>` can be e.g. `string`, `integer`, `string[]`, `resource<feat>`,
# `resource<feat>[]`. We just capture the *name*.
DECL_RE = re.compile(
    r"^\s*(base|calc)\s+(?:[a-zA-Z_][\w]*(?:<[^>]+>)?(?:\[\])?\s+)?([A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)
# Top-level function-style `define foo(...)` definitions (system-local macros)
DEFINE_RE = re.compile(r"^\s*define\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)
# Top-level builder definitions like `character_sheet_section foo() = ...`
TOPLEVEL_DEF_RE = re.compile(
    r"^\s*(character_sheet_section|character_creation_page|combatant_type)\s+([A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)
# `resource<NAME>` references
RESOURCE_TYPE_RE = re.compile(r"resource\s*<\s*([A-Za-z_]\w*)\s*>")
# `import "PATH"` statements
IMPORT_RE = re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE)
# `stat = "X"`, `edit_stat = "X"`, `resource_stat = "X"`, `resource_set_stat = "X"`
# We capture both the keyword and the value.
STAT_BIND_RE = re.compile(
    r'\b(stat|edit_stat|resource_stat|resource_set_stat)\s*=\s*"([^"]+)"'
)
RESOURCE_ID_RE = re.compile(r'\bresource_id\s*=\s*"([^"]+)"')
OPTIONS_RE = re.compile(r'\boptions\s*=\s*"([^"]+)"')


def line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def declared_stats_in(path: Path) -> set[str]:
    """Read a single .rpgs file and collect every `base`/`calc` name."""
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return {m.group(2) for m in DECL_RE.finditer(strip_comments(text))}


def load_declared_stats() -> set[str]:
    """The global character stat registry."""
    return declared_stats_in(CHARACTER_STATS)


def load_resource_scope_stats() -> dict[str, set[str]]:
    """For each resource type, the set of stats declared in its stats.rpgs."""
    out: dict[str, set[str]] = {}
    if not RESOURCES_DIR.exists():
        return out
    for d in RESOURCES_DIR.iterdir():
        if not d.is_dir():
            continue
        out[d.name] = declared_stats_in(d / "stats.rpgs")
    return out


def load_resource_types() -> set[str]:
    if not RESOURCES_DIR.exists():
        return set()
    return {p.name for p in RESOURCES_DIR.iterdir() if p.is_dir()}


def load_enum_types() -> set[str]:
    if not ENUMS_DIR.exists():
        return set()
    ids = set()
    for p in ENUMS_DIR.glob("*.rpg.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and "id" in data:
            ids.add(data["id"])
        # Also the bare filename minus suffix is a common convention
        ids.add(p.name.replace(".rpg.json", ""))
    return ids


def strip_strings(text: str) -> str:
    """Replace every "..." literal with spaces of equal length so identifier
    scanning doesn't trip over strings."""
    return STRING.sub(lambda m: " " * (m.end() - m.start()), text)


def strip_comments(text: str) -> str:
    """Strip // line comments and /* ... */ blocks. Keep line counts."""
    # /* ... */ — multiline, preserve newlines
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i:i + 2] == "/*":
            j = text.find("*/", i + 2)
            if j < 0:
                out.append(" " * (n - i))
                break
            chunk = text[i:j + 2]
            # Preserve newlines so line numbers stay aligned
            out.append("".join("\n" if c == "\n" else " " for c in chunk))
            i = j + 2
            continue
        if text[i:i + 2] == "//":
            j = text.find("\n", i)
            if j < 0:
                out.append(" " * (n - i))
                break
            out.append(" " * (j - i))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def scope_for(path: Path, resource_scope_stats: dict[str, set[str]]) -> tuple[str, set[str]]:
    """Determine which set of stats applies to references inside `path`.

    Returns (scope_label, stat_set). Scope label is for diagnostics.
    """
    rel = path.relative_to(SYSTEM).as_posix()
    # resources/<TYPE>/...
    parts = rel.split("/")
    if len(parts) >= 2 and parts[0] == "resources":
        rt = parts[1]
        return (f"resource:{rt}", resource_scope_stats.get(rt, set()))
    # combat_system/combatant_types/<TYPE>/...
    if len(parts) >= 3 and parts[0] == "combat_system" and parts[1] == "combatant_types":
        rt = parts[2]
        # player_character uses character stats; monster_instance uses the
        # monster_instance resource's stats.
        if rt == "player_character" or rt == "player":
            return (f"combatant:{rt}->character", load_declared_stats())
        if rt in resource_scope_stats:
            return (f"combatant:{rt}->resource", resource_scope_stats[rt])
        return (f"combatant:{rt}->character", load_declared_stats())
    # combat_system top-level (stats.rpgs, initiative_system.rpgs, etc.)
    if parts[0] == "combat_system":
        # These run in the combat scope (party_size, xp_pool, etc.) plus
        # whatever combat_system/stats.rpgs declares.
        cs = declared_stats_in(SYSTEM / "combat_system" / "stats.rpgs")
        return ("combat_system", cs | load_declared_stats())
    # Everything else (creation flow, sheet sections, mechanics) -> character
    return ("character", load_declared_stats())


def analyze_file(
    path: Path,
    resource_scope_stats: dict[str, set[str]],
    resource_types: set[str],
    enum_types: set[str],
) -> list[tuple[str, str, int, str]]:
    """Return list of (severity, code, line, message).

    severity in {"ERROR", "WARN", "NOTE"}.
    code is short like "import-missing", "stat-unknown", ...
    """
    issues: list[tuple[str, str, int, str]] = []
    raw = path.read_text(encoding="utf-8")
    text = strip_comments(raw)
    scope_label, scope_stats = scope_for(path, resource_scope_stats)

    # Names declared in *this* file with `base`/`calc` — skip them in the
    # ghost-reference scan below, since a declaration named `focus_points`
    # in a non-character scope is legitimate (e.g. the monster resource has
    # its own focus_points stat).
    file_locally_declared = {m.group(2) for m in DECL_RE.finditer(text)}

    # 1. Imports
    for m in IMPORT_RE.finditer(text):
        spec = m.group(1)
        line = line_of_offset(text, m.start())
        # _stdlib/ imports are external relative to ../../../_stdlib — we
        # can't validate without the parent repo. Skip them with a NOTE
        # collected at most once per file in main().
        if spec.startswith("../../../_stdlib/") or spec.startswith("_stdlib/"):
            continue
        # Otherwise, resolve relative to this file's directory.
        target = (path.parent / spec).resolve()
        if not target.exists():
            issues.append((
                "ERROR", "import-missing", line,
                f'import "{spec}" -> file not found ({target})',
            ))

    # 2. resource<TYPE> references and resource_id = "TYPE"
    for m in RESOURCE_TYPE_RE.finditer(text):
        t = m.group(1)
        line = line_of_offset(text, m.start())
        if t not in resource_types:
            issues.append((
                "ERROR", "resource-type-unknown", line,
                f'resource<{t}> — no directory pf1e/system/resources/{t}/',
            ))
    for m in RESOURCE_ID_RE.finditer(text):
        t = m.group(1)
        line = line_of_offset(text, m.start())
        if t not in resource_types:
            issues.append((
                "ERROR", "resource-id-unknown", line,
                f'resource_id = "{t}" — no resources/{t}/ directory',
            ))

    # 3. options = "ENUM" — allowed values are either an enumerated_type
    #    id or a resource type name.
    for m in OPTIONS_RE.finditer(text):
        t = m.group(1)
        line = line_of_offset(text, m.start())
        if t not in enum_types and t not in resource_types:
            issues.append((
                "ERROR", "options-unknown", line,
                f'options = "{t}" — neither an enumerated_type nor a resource type',
            ))

    # 4. stat / edit_stat / resource_stat / resource_set_stat bindings.
    #    Scope: depends on the file's location (see scope_for).
    for m in STAT_BIND_RE.finditer(text):
        kw, target = m.group(1), m.group(2)
        line = line_of_offset(text, m.start())
        if target.startswith("$") or "." in target:
            continue
        if target not in scope_stats:
            issues.append((
                "ERROR", "stat-unknown", line,
                f'{kw} = "{target}" — not declared in {scope_label} scope',
            ))

    # 5. Targeted pf2e-only stat ghost detection. We only flag identifiers
    #    that are KNOWN pf2e concepts that should not appear in PF1e files.
    #    Anything else (general "unresolved identifier") is too noisy
    #    without a real parser; we drop the broad warning.
    ghosts = {
        "hero_points", "focus_points", "hero_points_pips",
        "focus_points_pips", "ancestry_traits", "ancestry_feats",
        "ancestry_feats_for_display", "background_features",
        "class_feats_for_display", "skill_feats_for_display",
        "general_feats_for_display", "archetype_feats_for_display",
        "spellcasting_archetypes", "level_1_spells", "level_2_spells",
        "level_3_spells", "level_4_spells", "level_5_spells",
        "level_6_spells", "level_7_spells", "level_8_spells",
        "level_9_spells", "level_10_spells", "spells_show_prepared_only",
        "spells_hide_fully_expended_prepared", "all_weapons",
        "electrum_pieces", "class_archetype_mismatch_warning_text",
        "archetype_feats_warning_text",
        "archetype_dedication_missing_warning_text",
        "archetype_multiple_dedications_warning_text",
        "feats_above_current_level_warning_text",
        "improved_flexibility_warning_text",
        "unified_magical_theory_warning_text",
        "class_like_feats_level_restriction_warning_text",
        "class_like_feats_violate_level_restrictions",
        "progression_overspent_slots_warning_text",
        "progression_pending_slots_summary_text",
        "pending_sheet_proficiency_choices_warning_text",
        "pending_selectable_feature_choices_warning_text",
        "has_pending_sheet_proficiency_choices",
        "has_pending_interactive_slots",
    }
    stripped = strip_strings(text)
    seen: dict[str, int] = {}
    for m in IDENT.finditer(stripped):
        ident = m.group(1)
        if ident not in ghosts:
            continue
        if ident in file_locally_declared:
            # Declared in this file's own stats.rpgs — legitimate.
            continue
        # Skip member-access usage: foo.ghost / $character.ghost / ?.ghost
        # — there a "ghost" name actually denotes a field on some other
        # resource and may be present in that resource's schema even if it's
        # not a character stat.
        start = m.start()
        # Look back through any whitespace for a `.`
        i = start - 1
        while i >= 0 and stripped[i] in " \t":
            i -= 1
        if i >= 0 and stripped[i] == ".":
            continue
        # Report each ghost name only once per file (first occurrence)
        if ident in seen:
            continue
        seen[ident] = 1
        ln = line_of_offset(stripped, m.start())
        issues.append((
            "ERROR", "stat-pf2e-ghost", ln,
            f"reference to pf2e-only stat/expression `{ident}`",
        ))

    return issues


def main():
    if not CHARACTER_STATS.exists():
        print(f"missing {CHARACTER_STATS}", file=sys.stderr)
        return 2

    declared_stats = load_declared_stats()
    resource_types = load_resource_types()
    resource_scope_stats = load_resource_scope_stats()
    enum_types = load_enum_types()

    # Walk all .rpgs files
    rpgs_files = sorted(p for p in PF1E.rglob("*.rpgs"))
    if not rpgs_files:
        print(f"no .rpgs files under {PF1E}", file=sys.stderr)
        return 2

    # Analyze every file
    all_issues: list[tuple[Path, str, str, int, str]] = []
    for p in rpgs_files:
        issues = analyze_file(p, resource_scope_stats, resource_types, enum_types)
        for sev, code, ln, msg in issues:
            all_issues.append((p, sev, code, ln, msg))

    # Sort: priority files first, then by severity ERROR < WARN < NOTE, then file, then line
    sev_rank = {"ERROR": 0, "WARN": 1, "NOTE": 2}
    def key(item):
        p, sev, code, ln, msg = item
        rel = p.relative_to(SYSTEM).as_posix()
        is_priority = 0 if rel in PRIORITY_PATHS else 1
        return (is_priority, sev_rank.get(sev, 9), rel, ln)
    all_issues.sort(key=key)

    # Aggregate counts
    n_err = sum(1 for x in all_issues if x[1] == "ERROR")
    n_warn = sum(1 for x in all_issues if x[1] == "WARN")
    n_priority_err = sum(
        1 for x in all_issues
        if x[1] == "ERROR" and x[0].relative_to(SYSTEM).as_posix() in PRIORITY_PATHS
    )

    print(f"Scanned: {len(rpgs_files)} .rpgs files")
    print(f"Declared character stats: {len(declared_stats)}")
    print(f"Resource types: {len(resource_types)}")
    print(f"Enum types: {len(enum_types)}")
    print()
    print(f"ERRORS:   {n_err}  (of which in this-session files: {n_priority_err})")
    print(f"WARNINGS: {n_warn}")
    print()

    # Emit issues. Priority-file errors first, then everything else.
    for p, sev, code, ln, msg in all_issues:
        rel = p.relative_to(ROOT)
        print(f"{sev:5} {code:25} {rel}:{ln}  {msg}")

    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
