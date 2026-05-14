#!/usr/bin/env bash
# Regenerate every piece of content from data and validate.
# Usage: ./scripts/build_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Building classes..."
python3 scripts/build_core_classes.py

echo
echo "==> Building races..."
python3 scripts/build_core_races.py

echo
echo "==> Building weapons..."
python3 scripts/build_core_weapons.py

echo
echo "==> Building armor..."
python3 scripts/build_core_armor.py

echo
echo "==> Building feats (curated)..."
python3 scripts/build_core_feats.py

echo
echo "==> Building spells (curated)..."
python3 scripts/build_core_spells.py

echo
echo "==> Validating..."
python3 scripts/validate_resource_instances.py
