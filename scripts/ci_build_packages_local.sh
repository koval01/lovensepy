#!/usr/bin/env bash
# Local replica of GitHub Actions Nuitka packaging (macOS).
# Mirrors:
#   - .github/workflows/build-main-packages.yml  → job build-macos-arm64 (default)
#   - .github/workflows/build-macos-exe.yml      → with --tag
#
# Requirements: macOS, Xcode CLT (codesign), hdiutil, optional Homebrew (ccache).
# Python: 3.12 recommended (same as CI). A venv is created at .venv-nuitka-build/ so
# Homebrew PEP 668 ("externally-managed-environment") does not block pip.
#   PYTHON=/opt/homebrew/bin/python3.12 ./scripts/ci_build_packages_local.sh
#
# Windows onefile: see the "Build (Nuitka onefile)" step in build-main-packages.yml.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BOOTSTRAP_PYTHON="${PYTHON:-python3}"
NO_CCACHE=0
MODE="nightly"
VENV_DIR=""
RECREATE_VENV=0

usage() {
  echo "Usage: $0 [--tag] [--no-ccache] [--python EXEC] [--venv DIR] [--recreate-venv]"
  echo "  --tag            Tag workflow: no DMG rename, SHA256SUMS for full dist-nuitka/"
  echo "  --no-ccache      Skip brew install ccache (Nuitka may download its own)"
  echo "  --python EXEC    Interpreter used to create the venv (default: python3)"
  echo "  --venv DIR       Venv path (default: .venv-nuitka-build under repo root)"
  echo "  --recreate-venv  Remove venv and create again"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) MODE="tag" ;;
    --no-ccache) NO_CCACHE=1 ;;
    --recreate-venv) RECREATE_VENV=1 ;;
    --python)
      [[ $# -ge 2 ]] || usage
      BOOTSTRAP_PYTHON="$2"
      shift
      ;;
    --venv)
      [[ $# -ge 2 ]] || usage
      VENV_DIR="$2"
      shift
      ;;
    -h | --help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
  shift
done

[[ -n "$VENV_DIR" ]] || VENV_DIR="$ROOT/.venv-nuitka-build"
PYTHON="$VENV_DIR/bin/python"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script targets macOS (same as macos-latest ARM64 CI)." >&2
  exit 1
fi

echo "==> Bootstrap Python: $($BOOTSTRAP_PYTHON --version 2>&1)"

if [[ "$RECREATE_VENV" -eq 1 ]] && [[ -d "$VENV_DIR" ]]; then
  echo "==> Removing existing venv: $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "==> Creating venv: $VENV_DIR"
  "$BOOTSTRAP_PYTHON" -m venv "$VENV_DIR"
fi

echo "==> Build Python (venv): $($PYTHON --version 2>&1)"

if [[ "$NO_CCACHE" -eq 0 ]] && command -v brew >/dev/null 2>&1; then
  export HOMEBREW_NO_AUTO_UPDATE="${HOMEBREW_NO_AUTO_UPDATE:-1}"
  if brew list ccache &>/dev/null; then
    echo "==> ccache: already installed"
  else
    echo "==> Installing ccache (brew)"
    brew install ccache
  fi
else
  echo "==> Skipping ccache (--no-ccache or brew not found)"
fi

echo "==> pip install (into venv)"
"$PYTHON" -m pip install -U pip
"$PYTHON" -m pip install -e ".[service,ble]"
"$PYTHON" -m pip install "nuitka[onefile]"

echo "==> Nuitka build"
"$PYTHON" scripts/build_nuitka.py

APP="$ROOT/dist-nuitka/launcher.app"
if [[ ! -d "$APP" ]]; then
  echo "Missing $APP" >&2
  exit 1
fi

echo "==> codesign (ad-hoc)"
codesign --force --sign - --deep --preserve-metadata=entitlements "$APP"

echo "==> DMG"
bash scripts/package_macos_dmg.sh

if [[ "$MODE" == "nightly" ]]; then
  SHA7="$(git rev-parse --short=7 HEAD 2>/dev/null || echo local)"
  DMG_SRC="$ROOT/dist-nuitka/lovensepy-service-macos-arm64.dmg"
  DMG_DST="$ROOT/dist-nuitka/lovensepy-service-macos-arm64-${SHA7}.dmg"
  echo "==> Rename DMG (nightly-style): -> $(basename "$DMG_DST")"
  mv "$DMG_SRC" "$DMG_DST"
  echo "==> SHA256SUMS (DMG only, like CI artifact)"
  "$PYTHON" scripts/write_build_checksums.py --release-assets dist-nuitka
else
  echo "==> SHA256SUMS (full dist-nuitka/, tag workflow style)"
  "$PYTHON" scripts/write_build_checksums.py dist-nuitka
fi

echo ""
echo "Done. Contents of dist-nuitka:"
ls -la dist-nuitka
if [[ -f dist-nuitka/SHA256SUMS ]]; then
  echo ""
  echo "SHA256SUMS:"
  cat dist-nuitka/SHA256SUMS
fi
