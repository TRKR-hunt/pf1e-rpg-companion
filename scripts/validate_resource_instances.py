#!/usr/bin/env python3
import argparse
import gzip
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_STAT_PATTERN = re.compile(r"^base\s+([^\s]+)\s+([A-Za-z0-9_]+)\s*\(")
META_STATS = {"id", "updated_at"}


@dataclass(frozen=True)
class StatType:
    kind: str
    is_array: bool
    resource_type: Optional[str] = None

    def element_type(self) -> "StatType":
        return StatType(self.kind, False, self.resource_type)


def parse_type(type_token: str) -> StatType:
    is_array = type_token.endswith("[]")
    core = type_token[:-2] if is_array else type_token
    if core.startswith("resource<") and core.endswith(">"):
        return StatType("resource", is_array, core[len("resource<") : -1])
    if core == "resource":
        return StatType("resource", is_array, None)
    if core in {"string", "bool", "integer", "photo"}:
        return StatType(core, is_array, None)
    return StatType("unknown", is_array, None)


def load_schema(resources_root: Path) -> Dict[str, Dict[str, StatType]]:
    schema: Dict[str, Dict[str, StatType]] = {}
    for root, _dirs, files in os.walk(resources_root):
        if "stats.rpgs" not in files:
            continue
        resource_id = Path(root).name
        stats_path = Path(root) / "stats.rpgs"
        schema[resource_id] = parse_stats_file(stats_path)
    return schema


def parse_stats_file(path: Path) -> Dict[str, StatType]:
    stats: Dict[str, StatType] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("base "):
            continue
        match = BASE_STAT_PATTERN.match(stripped)
        if not match:
            continue
        type_token, stat_name = match.groups()
        stats[stat_name] = parse_type(type_token)
    return stats


def read_json(path: Path) -> Any:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode("utf-8-sig"))


def format_path(path_stack: List[str]) -> str:
    return " -> ".join(path_stack) if path_stack else "<root>"


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def resource_label(resource_obj: Dict[str, Any]) -> str:
    rid = resource_obj.get("resource_id")
    stats = resource_obj.get("stats")
    rid_text = f"resource_id='{rid}'" if isinstance(rid, str) else "resource_id<?>"
    if isinstance(stats, dict):
        stat_id = stats.get("id")
        if isinstance(stat_id, str) and stat_id:
            return f"{rid_text} (id='{stat_id}')"
    return rid_text


def add_error(
    errors: List[str],
    file_path: Path,
    repo_root: Path,
    path_stack: List[str],
    message: str,
) -> None:
    location = format_path(path_stack)
    errors.append(f"{display_path(file_path, repo_root)}: {location}: {message}")


def validate_resource_instance(
    resource_obj: Any,
    schema: Dict[str, Dict[str, StatType]],
    errors: List[str],
    file_path: Path,
    repo_root: Path,
    path_stack: List[str],
) -> None:
    if not isinstance(resource_obj, dict):
        add_error(
            errors,
            file_path,
            repo_root,
            path_stack,
            f"Expected object for resource, got {type(resource_obj).__name__}",
        )
        return

    rid = resource_obj.get("resource_id")
    if not isinstance(rid, str) or not rid:
        add_error(
            errors,
            file_path,
            repo_root,
            path_stack,
            "Missing or invalid resource_id",
        )
        return

    stats_schema = schema.get(rid)
    if stats_schema is None:
        add_error(
            errors,
            file_path,
            repo_root,
            path_stack + [f"resource_id='{rid}'"],
            "Unknown resource_id (no stats.rpgs found)",
        )
        return

    stats = resource_obj.get("stats")
    if not isinstance(stats, dict):
        add_error(
            errors,
            file_path,
            repo_root,
            path_stack + [resource_label(resource_obj)],
            f"Missing or invalid stats object, got {type(stats).__name__}",
        )
        return

    current_stack = path_stack + [resource_label(resource_obj)]
    for stat_name, stat_value in stats.items():
        if stat_name in META_STATS:
            continue
        stat_type = stats_schema.get(stat_name)
        if stat_type is None:
            add_error(
                errors,
                file_path,
                repo_root,
                current_stack + [f"stats.{stat_name}"],
                "Unknown stat for this resource",
            )
            continue
        if not isinstance(stat_value, dict) or "value" not in stat_value:
            add_error(
                errors,
                file_path,
                repo_root,
                current_stack + [f"stats.{stat_name}"],
                "Expected an object with a 'value' field",
            )
            continue
        validate_value(
            stat_value.get("value"),
            stat_type,
            schema,
            errors,
            file_path,
            repo_root,
            current_stack + [f"stats.{stat_name}.value"],
        )


def validate_value(
    value: Any,
    stat_type: StatType,
    schema: Dict[str, Dict[str, StatType]],
    errors: List[str],
    file_path: Path,
    repo_root: Path,
    path_stack: List[str],
) -> None:
    if value is None:
        return

    if stat_type.is_array:
        if not isinstance(value, list):
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack,
                f"Expected array, got {type(value).__name__}",
            )
            return
        element_type = stat_type.element_type()
        for idx, item in enumerate(value):
            if item is None and element_type.kind == "resource":
                continue
            validate_value(
                item,
                element_type,
                schema,
                errors,
                file_path,
                repo_root,
                path_stack + [f"[{idx}]"],
            )
        return

    kind = stat_type.kind
    if kind == "unknown":
        return
    if kind == "string":
        if not isinstance(value, str):
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack,
                f"Expected string, got {type(value).__name__}",
            )
        return
    if kind == "bool":
        if not isinstance(value, bool):
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack,
                f"Expected bool, got {type(value).__name__}",
            )
        return
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack,
                f"Expected number, got {type(value).__name__}",
            )
        return
    if kind == "photo":
        if not isinstance(value, dict):
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack,
                f"Expected photo object, got {type(value).__name__}",
            )
            return
        if "url" in value and not isinstance(value["url"], str):
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack + ["url"],
                f"Expected url string, got {type(value['url']).__name__}",
            )
        return
    if kind == "resource":
        if not isinstance(value, dict):
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack,
                f"Expected resource object, got {type(value).__name__}",
            )
            return
        expected = stat_type.resource_type
        actual = value.get("resource_id")
        if expected and actual != expected:
            add_error(
                errors,
                file_path,
                repo_root,
                path_stack,
                f"Expected resource_id '{expected}', got '{actual}'",
            )
        validate_resource_instance(
            value,
            schema,
            errors,
            file_path,
            repo_root,
            path_stack,
        )


def iter_instance_files(instances_root: Path) -> List[Path]:
    files: List[Path] = []
    for root, _dirs, filenames in os.walk(instances_root):
        for filename in filenames:
            if filename.startswith("."):
                continue
            if not filename.endswith((".json", ".rpg")):
                continue
            files.append(Path(root) / filename)
    return files


def infer_system_from_path(path: Path, repo_root: Path) -> Optional[str]:
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None
    parts = list(rel.parts)
    for idx, part in enumerate(parts):
        if part == "systems" and idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def discover_pf1e_layout(repo_root: Path) -> Optional[tuple]:
    """Find (resources_root, instances_root, enum_root, rpgs_search_roots) for pf1e-work
    repos which use `<system>/system/...` directly under the repo root, not under
    a `systems/` wrapper. Falls back to None if not found."""
    for cand in repo_root.iterdir() if repo_root.is_dir() else []:
        if not cand.is_dir():
            continue
        sys_dir = cand / "system"
        inst_dir = cand / "resource_instances"
        if (sys_dir / "resources").is_dir() and inst_dir.is_dir():
            return (
                sys_dir / "resources",
                inst_dir,
                sys_dir / "enumerated_types",
                [sys_dir],
            )
    return None


def parse_enum_definitions(enum_root: Path) -> Dict[str, set]:
    """Read every <enum>.rpg.json under enumerated_types/ and return id → set(of ids)."""
    enums: Dict[str, set] = {}
    extends: Dict[str, str] = {}
    if not enum_root.is_dir():
        return enums
    for f in enum_root.iterdir():
        if not f.name.endswith(".rpg.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        eid = data.get("id")
        if not isinstance(eid, str):
            continue
        ids = set()
        for t in data.get("types", []) or []:
            if isinstance(t, dict) and isinstance(t.get("id"), str):
                ids.add(t["id"])
        enums[eid] = ids
        parent = data.get("extends_type")
        if isinstance(parent, str):
            extends[eid] = parent
    # Resolve extends chains (one pass is enough for our depth).
    for child, parent in list(extends.items()):
        if parent in enums:
            enums[child] = enums[child] | enums[parent]
    return enums


# --- formula-reference checker (catches PathNotFoundException-class errors) ---
#
# Catches two classes of bug:
#  (a) $character.X where X isn't declared on the character.
#  (b) $character.A.B or $character.A?.B?.C where deeper segments don't exist
#      on the resource type that A resolves to.
#
# Sources scanned:
#  - every *.rpgs under the system tree (calc/base formula bodies)
#  - system.rpg.json (top-level system definition, hand-written JSON with
#    "stat": "X" view bindings and effect targets). This is where the
#    level-up flow lives; we missed P4 originally because we only scanned .rpgs.

# Matches $character or $character? followed by `.X` or `?.X` chains of any
# length. Captures the full chain (without the $character prefix) including
# `?.` separators and trailing `?` segments.
CHARACTER_CHAIN_RE = re.compile(
    r"\$character\??\.([a-z_][a-z0-9_]*(?:\??\.[a-z_][a-z0-9_]*)*\??)"
)

# Match `^base|calc <type> <name>(` to extract declared stat names.
# Reuses BASE_STAT_PATTERN-style approach but allows `calc` too.
DECL_RE = re.compile(r"^(?:base|calc)\s+([^\s]+)\s+([a-z_][a-z0-9_]*)\s*\(", re.MULTILINE)


def parse_declared_character_stats(character_stats_path: Path) -> Dict[str, StatType]:
    """Return name -> StatType for every base/calc declaration in character_stats.rpgs."""
    if not character_stats_path.is_file():
        return {}
    text = character_stats_path.read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)
    out: Dict[str, StatType] = {}
    for type_token, name in DECL_RE.findall(text):
        out[name] = parse_type(type_token)
    return out


def parse_resource_type_fields(resources_root: Path) -> Dict[str, Dict[str, StatType]]:
    """Return resource_id -> {field_name: StatType} for every resource type's stats.rpgs.

    This is essentially load_schema() but pre-existing call sites use that for
    a slightly different purpose; keep both for clarity."""
    out: Dict[str, Dict[str, StatType]] = {}
    if not resources_root.is_dir():
        return out
    for child in resources_root.iterdir():
        stats_path = child / "stats.rpgs"
        if not stats_path.is_file():
            continue
        rid = child.name
        text = re.sub(r"//[^\n]*", "", stats_path.read_text(encoding="utf-8"))
        fields: Dict[str, StatType] = {}
        for type_token, name in DECL_RE.findall(text):
            fields[name] = parse_type(type_token)
        out[rid] = fields
    return out


# Meta-fields implicitly present on every resource instance (sourced from
# the file's `id` field or the bundling manifest, not from stats.rpgs).
RESOURCE_META_FIELDS = {"id", "updated_at"}


def _validate_chain(
    chain: str,
    declared_character_stats: Dict[str, StatType],
    resource_type_fields: Dict[str, Dict[str, StatType]],
) -> Optional[str]:
    """Walk a `.A.B?.C?` chain starting from $character.
    Returns None if every segment resolves, else an error explanation."""
    segments = re.split(r"\??\.", chain)
    segments = [s.rstrip("?") for s in segments if s]
    if not segments:
        return None
    head = segments[0]
    head_type = declared_character_stats.get(head)
    if head_type is None:
        return f"$character.{head}: not declared in character_stats.rpgs"
    if len(segments) == 1:
        return None
    current_type = head_type
    walked = ["$character", head]
    for seg in segments[1:]:
        if current_type.kind != "resource":
            return (
                f"{'.'.join(walked)}.{seg}: parent has type '{current_type.kind}' "
                f"(no fields can be looked up on a non-resource)"
            )
        rid = current_type.resource_type
        if rid is None:
            return None  # untyped resource — can't resolve further but valid
        # `id`/`updated_at` are implicit on every resource instance.
        if seg in RESOURCE_META_FIELDS:
            current_type = StatType("string", False, None)
            walked.append(seg)
            continue
        rtype_fields = resource_type_fields.get(rid)
        if rtype_fields is None:
            return f"{'.'.join(walked)}.{seg}: resource type '{rid}' has no stats.rpgs"
        seg_type = rtype_fields.get(seg)
        if seg_type is None:
            return (
                f"{'.'.join(walked)}.{seg}: '{seg}' is not declared on resource type '{rid}'"
            )
        current_type = seg_type
        walked.append(seg)
    return None


def _blank_string_literals(text: str) -> str:
    """Replace contents inside double-quoted string literals with spaces, so
    regex scans don't flag `$character.foo` that appears inside metaStat(...)
    or concat([...]) templates (those are dynamic-path constructions, not
    direct dereferences). Preserves line numbers."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            out.append('"')
            j = i + 1
            while j < n:
                cj = text[j]
                if cj == '\\' and j + 1 < n:
                    # preserve the escape pair as spaces; keeps newline counting honest
                    out.append("  " if text[j + 1] != "\n" else " \n")
                    j += 2
                    continue
                if cj == '"':
                    out.append('"')
                    j += 1
                    break
                out.append("\n" if cj == "\n" else " ")
                j += 1
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def validate_character_refs(
    rpgs_search_roots: List[Path],
    declared_character_stats: Dict[str, StatType],
    resource_type_fields: Dict[str, Dict[str, StatType]],
    errors: List[str],
    repo_root: Path,
) -> None:
    """Scan every .rpgs under the search roots for `$character.A?.B?.C` chains
    and report any chain segment that doesn't resolve.

    Catches the PathNotFoundException family — formulas that compile clean
    but throw at runtime when the path is dereferenced."""
    if not declared_character_stats:
        # No declared stats found — refuse to silently pass.
        return
    for root in rpgs_search_roots:
        for rpgs in root.rglob("*.rpgs"):
            try:
                text = rpgs.read_text(encoding="utf-8")
            except Exception:
                continue
            stripped = re.sub(r"//[^\n]*", "", text)
            stripped = _blank_string_literals(stripped)
            for m in CHARACTER_CHAIN_RE.finditer(stripped):
                chain = m.group(1)
                problem = _validate_chain(chain, declared_character_stats, resource_type_fields)
                if problem is None:
                    continue
                line = stripped.count("\n", 0, m.start()) + 1
                add_error(
                    errors,
                    rpgs,
                    repo_root,
                    [f"line {line}"],
                    f"{problem} (will throw PathNotFoundException at load)",
                )


def validate_system_json_stat_refs(
    rpgs_search_roots: List[Path],
    declared_character_stats: Dict[str, StatType],
    errors: List[str],
    repo_root: Path,
) -> None:
    """Scan system.rpg.json (top-level system def, hand-written JSON) for
    bare `"stat": "X"` view bindings and effect targets where X is meant to
    be a character stat. Report any X that isn't declared.

    Catches the class of bug where a view in system.rpg.json (e.g. the
    level-up `select` view) binds to a character stat that was never
    declared on character_stats.rpgs — the runtime throws when constructing
    the view because the stat doesn't exist."""
    if not declared_character_stats:
        return
    for root in rpgs_search_roots:
        candidate = root / "system.rpg.json"
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except Exception:
            continue
        # Find every `"stat": "X"` pair. Skip $-prefixed paths (view-local,
        # lambda, etc.) and dotted paths (those reference fields on resources,
        # not character stats at the top level).
        for m in re.finditer(r'"stat"\s*:\s*"([^"$.]+)"', text):
            stat = m.group(1)
            if stat in declared_character_stats:
                continue
            line = text.count("\n", 0, m.start()) + 1
            add_error(
                errors,
                candidate,
                repo_root,
                [f"line {line}"],
                f"\"stat\": \"{stat}\" — stat is not declared in character_stats.rpgs "
                f"(will throw at runtime when this view/effect materialises)",
            )


# Curated (resource_id, field_name) → enum_name map. This is more reliable
# than scraping .rpgs source because most enum lookups happen inside formulas
# that reference stats via $-paths (e.g. `enumeratedName(enumerated_type="X",
# id=$mapValue.kind)`), where the tail token is a lambda var, not a stat name.
# Entries below are the well-known enum-typed stat fields per resource type;
# extend as we surface more.
CURATED_ENUM_FIELDS: Dict[tuple, str] = {
    # feat
    ("feat", "type"): "feat_types",
    ("feat", "action_cost"): "action_types",
    # effect
    ("effect", "type"): "effect_types",
    ("effect", "trigger_type"): "effect_trigger_types",
    ("effect", "typed_modifier_type"): "effect_typed_modifier_types",
    ("effect", "typed_modifier_polarity"): "effect_modifier_polarities",
    ("effect", "aggregation_type"): "effect_aggregation_types",
    ("effect", "charge_type"): "charge_types",
    # spell
    ("spell", "school"): "spell_school",
    # race
    ("race", "size"): "sizes",
    # weapon
    ("weapon", "damage_type"): "damage_types",
    # armor
    ("armor", "category"): "armor_types",
}


def validate_enum_memberships(
    instances_root: Path,
    enum_defs: Dict[str, set],
    errors: List[str],
    repo_root: Path,
) -> None:
    """Second pass: for each instance, walk it with resource-type context and
    check string-valued enum fields against the curated map."""
    if not enum_defs:
        return
    for path in iter_instance_files(instances_root):
        try:
            data = read_json(path)
        except Exception:
            continue
        _walk_for_enum_check(data, enum_defs, errors, path, repo_root, [])


def _walk_for_enum_check(
    node: Any,
    enum_defs: Dict[str, set],
    errors: List[str],
    file_path: Path,
    repo_root: Path,
    path_stack: List[str],
) -> None:
    """Walk a JSON tree, tracking the current resource_id context. When we hit
    a `{resource_id, stats: {...}}` object, descend into stats with that rid
    as context. At each `(rid, key)` whose value is a `{value: X}` wrapper
    that maps to a curated enum, check X against the enum's allowed ids."""
    if not isinstance(node, dict):
        if isinstance(node, list):
            for i, item in enumerate(node):
                _walk_for_enum_check(item, enum_defs, errors, file_path, repo_root, path_stack + [f"[{i}]"])
        return
    rid = node.get("resource_id") if isinstance(node.get("resource_id"), str) else None
    stats = node.get("stats")
    if rid and isinstance(stats, dict):
        for k, v in stats.items():
            enum_name = CURATED_ENUM_FIELDS.get((rid, k))
            if enum_name and isinstance(v, dict) and "value" in v:
                val = v["value"]
                vals = val if isinstance(val, list) else [val]
                for one in vals:
                    if not isinstance(one, str) or one == "":
                        # Empty string means "unset"; runtime treats as default.
                        # Not an enum-id mismatch.
                        continue
                    valid_ids = enum_defs.get(enum_name)
                    if valid_ids is None:
                        continue
                    if one not in valid_ids:
                        add_error(
                            errors,
                            file_path,
                            repo_root,
                            path_stack + [f"stats.{k}.value"],
                            f"Enum '{enum_name}' has no id '{one}'. "
                            f"Allowed: {sorted(valid_ids)[:8]}{'…' if len(valid_ids) > 8 else ''}",
                        )
            # Recurse into the value to find nested resources.
            _walk_for_enum_check(
                v, enum_defs, errors, file_path, repo_root, path_stack + [f"stats.{k}"]
            )
        return
    # Not a resource wrapper — keep descending.
    for k, v in node.items():
        _walk_for_enum_check(v, enum_defs, errors, file_path, repo_root, path_stack + [str(k)])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate resource instance JSON against system stats.rpgs schema.",
    )
    parser.add_argument(
        "--system",
        default=None,
        help="System folder name under systems/ (upstream layout) or directly under repo root (pf1e-work layout).",
    )
    parser.add_argument(
        "--instances",
        default=None,
        help="Override resource_instances path",
    )
    parser.add_argument(
        "--resources",
        default=None,
        help="Override resources/ path (where each resource type's stats.rpgs lives)",
    )
    parser.add_argument(
        "--enum-root",
        default=None,
        help="Override enumerated_types/ path",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Validate a single resource instance file",
    )
    parser.add_argument(
        "--no-enum-check",
        action="store_true",
        help="Skip the enum-membership second pass.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    # Auto-detect repo layout. Two supported shapes:
    #   Upstream:   <repo>/systems/<sys>/system/{resources,enumerated_types,...}
    #                                       /resource_instances/
    #   pf1e-work:  <repo>/<sys>/system/{resources,enumerated_types,...}
    #                          /resource_instances/
    resources_root: Optional[Path] = None
    instances_root: Optional[Path] = None
    enum_root: Optional[Path] = None
    rpgs_search_roots: List[Path] = []

    if args.resources or args.instances:
        if args.resources:
            resources_root = Path(args.resources)
        if args.instances:
            instances_root = Path(args.instances)
        if args.enum_root:
            enum_root = Path(args.enum_root)
        else:
            # Try to infer from resources_root: same parent.
            if resources_root and resources_root.parent.is_dir():
                cand = resources_root.parent / "enumerated_types"
                if cand.is_dir():
                    enum_root = cand
        if resources_root and resources_root.parent.is_dir():
            rpgs_search_roots.append(resources_root.parent)
    else:
        layout = discover_pf1e_layout(repo_root)
        if layout:
            resources_root, instances_root, enum_root, rpgs_search_roots = layout
        else:
            system_name = args.system or "5e"
            system_root = repo_root / "systems" / system_name
            resources_root = system_root / "system" / "resources"
            instances_root = system_root / "resource_instances"
            enum_root = system_root / "system" / "enumerated_types"
            rpgs_search_roots = [system_root / "system"]

    if not resources_root or not resources_root.is_dir():
        print(f"Missing resources folder: {resources_root}", file=sys.stderr)
        return 2

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"Missing file: {file_path}", file=sys.stderr)
            return 2
    elif not instances_root or not instances_root.is_dir():
        print(f"Missing resource_instances folder: {instances_root}", file=sys.stderr)
        return 2

    schema = load_schema(resources_root)
    errors: List[str] = []
    instance_files = [Path(args.file)] if args.file else iter_instance_files(instances_root)

    for path in instance_files:
        try:
            data = read_json(path)
        except Exception as exc:  # noqa: BLE001 - report parse issues
            add_error(
                errors,
                path,
                repo_root,
                [],
                f"Failed to parse JSON: {exc}",
            )
            continue
        validate_resource_instance(data, schema, errors, path, repo_root, [])

    # Enum-membership second pass (uses curated (resource_id, field) → enum map).
    if not args.no_enum_check and enum_root and instances_root:
        enum_defs = parse_enum_definitions(enum_root)
        validate_enum_memberships(instances_root, enum_defs, errors, repo_root)

    # Formula-reference pass: dangling $character.X formula references,
    # including chained $character.A?.B?.C references that walk into resource
    # types. Also checks "stat": "X" bindings in system.rpg.json.
    if rpgs_search_roots:
        char_stats_path = None
        for r in rpgs_search_roots:
            cand = r / "character_stats.rpgs"
            if cand.is_file():
                char_stats_path = cand
                break
        if char_stats_path:
            declared = parse_declared_character_stats(char_stats_path)
            resource_type_fields = parse_resource_type_fields(resources_root) if resources_root else {}
            validate_character_refs(
                rpgs_search_roots, declared, resource_type_fields, errors, repo_root
            )
            validate_system_json_stat_refs(
                rpgs_search_roots, declared, errors, repo_root
            )

    if errors:
        print("Validation errors:", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        print(f"{len(errors)} error(s) found in {len(instance_files)} file(s).", file=sys.stderr)
        return 1

    print(f"OK: {len(instance_files)} resource instance file(s) validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
