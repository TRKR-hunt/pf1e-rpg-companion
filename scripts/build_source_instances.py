#!/usr/bin/env python3
"""Build/refresh `source` resource instances from references in resource_instances/.

Idempotent. Walks every non-source resource instance, collects each unique
`source` id it references, plus an always-present baseline (CRB + the
canonical PF1e books listed in scrape_lib.KNOWN_SOURCES + the "unknown"
fallback + the "3pp" third-party bucket). For each, writes a canonical
source_<id>.rpg.json. Hand-curated abbreviations come from
scrape_lib.KNOWN_SOURCES; auto-derived ones use an acronym of significant
tokens in the id.

Drops any source_*.rpg.json that's not referenced anywhere.

Re-run after any scraper run that may have introduced new books, OR after
manually correcting the source field on a hand-curated resource.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scrape_lib

OUT_DIR = Path(__file__).parent.parent / "pf1e" / "resource_instances"

# IDs that should always exist even if nothing currently references them.
ALWAYS_PRESENT = {
    "crb", "apg", "acg", "arg",
    "um", "uc", "ui", "uw", "ucamp", "upsi",
    "iswg", "isg", "isr",
    "3pp", "unknown",
}

# Hand-tuned abbreviations for IDs that need them.
TUNED_ABBR = {v[0]: v[1] for v in scrape_lib.KNOWN_SOURCES.values()}
TUNED_ABBR.update({
    "3pp": "3PP",
    "unknown": "?",
})

STOP_WORDS = {"of", "the", "and", "to", "for", "in", "on",
              "a", "an", "or", "s"}


def _auto_abbr(sid: str) -> str:
    tokens = sid.replace("_", " ").split()
    sig = [t for t in tokens if t.lower() not in STOP_WORDS]
    abbr = "".join(t[0].upper() for t in sig if t and t[0].isalpha())[:6]
    return abbr or "?"


def main():
    referenced: set[str] = set()
    for f in OUT_DIR.glob("*.rpg.json"):
        if f.name.startswith("source_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        sid = data.get("stats", {}).get("source", {}).get("value")
        if sid:
            referenced.add(sid)

    needed = referenced | ALWAYS_PRESENT
    existing = {p.name[len("source_"):-len(".rpg.json")]
                for p in OUT_DIR.glob("source_*.rpg.json")}

    written = 0
    for sid in sorted(needed):
        abbr = TUNED_ABBR.get(sid) or _auto_abbr(sid)
        inst = {
            "resource_id": "source",
            "stats": {
                "id": sid,
                "abbreviation": {"value": abbr},
            },
        }
        (OUT_DIR / f"source_{sid}.rpg.json").write_text(
            json.dumps(inst, indent=2), encoding="utf-8"
        )
        written += 1

    orphans = existing - needed
    for sid in sorted(orphans):
        (OUT_DIR / f"source_{sid}.rpg.json").unlink()

    print(f"Referenced source ids: {len(referenced)}")
    print(f"Always-present baseline: {len(ALWAYS_PRESENT)}")
    print(f"Wrote {written} source instances, dropped {len(orphans)} orphans.")
    if orphans:
        for sid in sorted(orphans):
            print(f"  - dropped source_{sid}")


if __name__ == "__main__":
    main()
