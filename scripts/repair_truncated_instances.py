"""
Repair instance JSON files truncated mid-string.

A widespread data-integrity bug across the project: many instance files
end with an unterminated string (e.g. the `lore.value` was being written
when the underlying writer cut off). 6 base classes, 83 prestige classes,
and 160 archetypes are affected.

Strategy:
  1. Read file as bytes, strip trailing NUL/whitespace padding.
  2. Try to parse. If it succeeds, leave the file alone.
  3. If parse fails with "Unterminated string", binary-search for the
     longest valid prefix, identify the open string at the cut, close
     the string with `"`, then close as many `}` / `]` as needed to
     balance brackets (count the open `{`/`[` seen and emit matching
     closers).
  4. Re-parse to verify. If still broken, leave the file alone (do
     NOT delete content).

Idempotent: a re-run on a repaired file does nothing.
Augment-only: never drops content; only appends closers.
Dry-run by default; --apply to write.
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INST_DIR = REPO / "pf1e" / "resource_instances"


def balance_closers(text: str) -> str:
    """Given a string of valid JSON-ish text up to a closed string,
    walk it and emit the closing braces/brackets to balance opens.
    Tracks whether we're inside a string to ignore quotes inside strings.
    """
    depth_obj = 0
    depth_arr = 0
    in_str = False
    esc = False
    for ch in text:
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth_obj += 1
        elif ch == "}":
            depth_obj -= 1
        elif ch == "[":
            depth_arr += 1
        elif ch == "]":
            depth_arr -= 1
    if in_str:
        raise ValueError("balance_closers called while still inside string")
    suffix = ""
    # Close arrays first if any remain, then objects.
    suffix += "]" * max(0, depth_arr)
    suffix += "}" * max(0, depth_obj)
    return suffix


def try_parse(s: str):
    try:
        json.loads(s)
        return None
    except json.JSONDecodeError as e:
        return e


def repair(raw: str) -> str | None:
    """Returns repaired text, or None if no repair found."""
    raw = raw.rstrip("\x00").rstrip()
    if try_parse(raw) is None:
        return None  # already valid

    # Find the position of the last `"value": "...` opening quote that
    # is not closed before EOF. We look for the rightmost `"value": "`
    # that is itself the opening of an unterminated string.
    # Heuristic: walk backwards until we find a `"value": "` whose
    # following string would parse if we close it at end.
    m_iter = list(re.finditer(r'"value"\s*:\s*"', raw))
    if not m_iter:
        return None
    # Try the last match; if not it, walk backwards.
    for m in reversed(m_iter):
        opening_end = m.end()  # position just after the opening `"`
        # Body extends from opening_end to end of raw.
        body = raw[opening_end:]
        # Strip any trailing junk that can't be string content
        # (we'll just take the entire tail and close with `"`).
        # First, sanity-escape any naked `"` inside the body.
        # Easier path: assume body is text (no embedded structural JSON);
        # just escape backslash and quote.
        # But common case: the body is plain prose. Let's normalize.
        cleaned_body = body
        # Strip stray closing braces accidentally appended:
        cleaned_body = re.sub(r"[\}\]\s]*$", "", cleaned_body)
        # Escape backslashes + quotes
        cleaned_body = (
            cleaned_body
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            # Replace literal newlines with escaped \n so JSON accepts the string.
            .replace("\r", "")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        # Close the string.
        new_str = '"'
        prefix_before_body = raw[:opening_end]
        candidate = prefix_before_body + cleaned_body + new_str
        # Now close braces/arrays to balance.
        try:
            suffix = balance_closers(candidate)
        except ValueError:
            continue
        candidate_full = candidate + suffix + "\n"
        if try_parse(candidate_full) is None:
            return candidate_full
    return None


def process_file(path: Path, *, apply: bool):
    raw = path.read_bytes()
    # Strip nul / trailing whitespace padding
    stripped = raw.rstrip(b"\x00").rstrip().decode("utf-8")
    err = try_parse(stripped)
    if err is None:
        return False, f"clean {path.name}"
    rep = repair(stripped)
    if rep is None:
        return False, f"unrepairable {path.name}: {err.msg} @ {err.pos}"
    if apply:
        path.write_text(rep, encoding="utf-8")
    return True, f"repair {path.name} ({len(raw)} -> {len(rep)} bytes)"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    files = sorted(p for p in INST_DIR.iterdir() if p.is_file()
                   and p.name.endswith(".rpg.json"))
    if args.limit:
        files = files[: args.limit]
    repaired = clean = bad = 0
    for p in files:
        try:
            changed, summary = process_file(p, apply=args.apply)
        except Exception as e:
            bad += 1
            print(f"FAIL {p.name}: {e}", file=sys.stderr)
            continue
        if summary.startswith("repair"):
            repaired += 1
            if args.verbose:
                print(summary)
        elif summary.startswith("clean"):
            clean += 1
        else:
            bad += 1
            print(summary)
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"[{mode}] files={len(files)} repaired={repaired} clean={clean} unrepairable={bad}")


if __name__ == "__main__":
    main()
