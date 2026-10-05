#!/usr/bin/env bash
# Build Mac release zip (source + start.command) — by Pixam
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER="$(python3 -c "import json; print(json.load(open('version.json'))['version'])")"
NAME="PSHomebrewDesk-mac"
STAGE="$(mktemp -d)/${NAME}"
mkdir -p "$STAGE"
rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '.iconbuild' \
  --exclude 'cache' \
  --exclude 'vendor' \
  --exclude 'build' \
  --exclude 'dist' \
  --exclude 'catalog/files/*' \
  --exclude 'updates/*.zip' \
  --exclude 'updates/manifest.json' \
  --exclude 'payloads/*.elf' \
  --exclude 'payloads/*.bin' \
  --exclude 'payloads/*.pkg' \
  --exclude '.DS_Store' \
  --exclude 'community/discord/.env' \
  --exclude '*.zip' \
  ./ "$STAGE/"
mkdir -p "$STAGE/catalog/files" "$STAGE/cache" "$STAGE/payloads" "$STAGE/updates"
touch "$STAGE/catalog/files/.gitkeep" "$STAGE/updates/.gitkeep"
OUT="${1:-$ROOT/dist/${NAME}.zip}"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
(cd "$(dirname "$STAGE")" && zip -qry "$OUT" "$(basename "$STAGE")")
echo "OK $OUT (v$VER)"
ls -lh "$OUT"
