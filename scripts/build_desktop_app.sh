#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/desktop_common.sh"

UNSIGNED=0
TARGET_OVERRIDE=""

usage() {
  cat <<'EOF'
Build a local desktop installer in one command.

Usage:
  ./scripts/build_desktop_app.sh [options]

Options:
  --target <triple>     Override target triple (default: host target).
  --unsigned            Build installer without updater artifacts/signing.
  -h, --help            Show this help.

Examples:
  # Signed build (requires Tauri signing env or key file)
  export TAURI_SIGNING_PRIVATE_KEY_PASSWORD='your-password'
  ./scripts/build_desktop_app.sh

  # Unsigned local build (no signing key/password required)
  ./scripts/build_desktop_app.sh --unsigned
EOF
}

log() {
  printf '[desktop-build] %s\n' "$*"
}

fail() {
  printf '[desktop-build][error] %s\n' "$*" >&2
  exit 1
}

prepare_signing_env() {
  if [[ "$UNSIGNED" -eq 1 ]]; then
    return
  fi

  local key_path="${TAURI_KEY_PATH:-$HOME/.tauri/aws-cost-optimizer.key}"
  if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    desktop_common_load_signing_key "$key_path" || fail "Could not load TAURI signing key."
    log "Loaded TAURI_SIGNING_PRIVATE_KEY from $key_path"
  fi

  [[ -n "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" ]] \
    || fail "Set TAURI_SIGNING_PRIVATE_KEY_PASSWORD or use --unsigned."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      [[ $# -ge 2 ]] || fail "Missing value for --target"
      TARGET_OVERRIDE="$2"
      shift 2
      ;;
    --unsigned)
      UNSIGNED=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1 (use --help)"
      ;;
  esac
done

desktop_common_need_cmd python3 || fail "Missing required command: python3"
desktop_common_need_cmd npm || fail "Missing required command: npm"
desktop_common_need_cmd cargo || fail "Missing required command: cargo"
desktop_common_need_cmd rg || fail "Missing required command: rg"

TARGET="${TARGET_OVERRIDE:-$(desktop_common_resolve_host_target)}"
SUFFIX="$(desktop_common_target_suffix "$TARGET")"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/python3" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python3"
  elif [[ -x "$ROOT_DIR/server/venv/bin/python3" ]]; then
    PYTHON_BIN="$ROOT_DIR/server/venv/bin/python3"
  else
    PYTHON_BIN="python3"
  fi
fi

prepare_signing_env

log "Repository root: $ROOT_DIR"
log "Target: $TARGET"
log "Python: $PYTHON_BIN"
if [[ "$UNSIGNED" -eq 1 ]]; then
  log "Mode: unsigned (skips updater artifact signing)"
else
  log "Mode: signed"
fi

log "Installing Python bundle dependencies..."
"$PYTHON_BIN" -m pip install -r "$ROOT_DIR/server/requirements-bundle.txt"

log "Building Python sidecar with PyInstaller..."
(
  cd "$ROOT_DIR/server"
  "$PYTHON_BIN" -m PyInstaller aws-cost-optimizer-api.spec
)

SRC="$ROOT_DIR/server/dist/aws-cost-optimizer-api${SUFFIX}"
DST="$ROOT_DIR/client/src-tauri/binaries/aws-cost-optimizer-api-${TARGET}${SUFFIX}"
[[ -f "$SRC" ]] || fail "Expected sidecar binary not found at $SRC"
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
log "Sidecar copied to $DST"

log "Installing frontend dependencies..."
npm --prefix "$ROOT_DIR/client" ci

TAURI_ARGS=(build --target "$TARGET")
if [[ "$UNSIGNED" -eq 1 ]]; then
  TAURI_ARGS+=(--config '{"bundle":{"createUpdaterArtifacts":false}}')
fi

log "Building Tauri installer..."
npm --prefix "$ROOT_DIR/client" run tauri -- "${TAURI_ARGS[@]}"

MAC_DMG="$ROOT_DIR/client/src-tauri/target/$TARGET/release/bundle/dmg"
WIN_MSI="$ROOT_DIR/client/src-tauri/target/$TARGET/release/bundle/msi"
LINUX_APPIMAGE="$ROOT_DIR/client/src-tauri/target/$TARGET/release/bundle/appimage"

if [[ -d "$MAC_DMG" ]]; then
  log "Build complete. DMG output:"
  find "$MAC_DMG" -maxdepth 1 -type f -name '*.dmg' -print
elif [[ -d "$WIN_MSI" ]]; then
  log "Build complete. Windows installer output:"
  find "$WIN_MSI" -maxdepth 1 -type f -name '*.msi' -print
elif [[ -d "$LINUX_APPIMAGE" ]]; then
  log "Build complete. Linux installer output:"
  find "$LINUX_APPIMAGE" -maxdepth 1 -type f -name '*.AppImage' -print
else
  log "Build complete. Check client/src-tauri/target/$TARGET/release/bundle/"
fi
