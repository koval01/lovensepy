#!/usr/bin/env bash
set -euo pipefail

# Create a simple DMG containing the built .app.
#
# Expected input:
#   dist-nuitka/launcher.app
#
# Output:
#   dist-nuitka/lovensepy-service-macos-arm64.dmg

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

APP_PATH="dist-nuitka/launcher.app"
DMG_PATH="dist-nuitka/lovensepy-service-macos-arm64.dmg"
STAGE_DIR="dist-nuitka/dmg-stage"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Expected app bundle at $APP_PATH" >&2
  exit 1
fi

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# Presentable name for end-users.
cp -R "$APP_PATH" "$STAGE_DIR/LovensePy Service.app"

# Recreate DMG (no compression flags for maximum compatibility).
rm -f "$DMG_PATH"
hdiutil create \
  -volname "LovensePy Service" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "Created $DMG_PATH"

