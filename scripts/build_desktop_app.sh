#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

need_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
}

resolve_host_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os" in
    Darwin)
      case "$arch" in
        arm64|aarch64) echo "aarch64-apple-darwin" ;;
        x86_64) echo "x86_64-apple-darwin" ;;
        *) fail "Unsupported macOS architecture: $arch" ;;
      esac
      ;;
    Linux)
      case "$arch" in
        x86_64|amd64) echo "x86_64-unknown-linux-gnu" ;;
        aarch64|arm64) echo "aarch64-unknown-linux-gnu" ;;
        *) fail "Unsupported Linux architecture: $arch" ;;
      esac
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      echo "x86_64-pc-windows-msvc"
      ;;
    *)
      fail "Unsupported OS for desktop build: $os"
      ;;
  esac
}

target_suffix() {
  local target="$1"
  case "$target" in
    *windows*) echo ".exe" ;;
    *) echo "" ;;
  esac
}

prepare_signing_env() {
  if [[ "$UNSIGNED" -eq 1 ]]; then
    return
  fi

  if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    local key_path="${TAURI_KEY_PATH:-$HOME/.tauri/aws-cost-optimizer.key}"
    [[ -f "$key_path" ]] || fail "Missing key file: $key_path (or set TAURI_SIGNING_PRIVATE_KEY)."
    TAURI_SIGNING_PRIVATE_KEY="$(cat "$key_path")"
    export TAURI_SIGNING_PRIVATE_KEY
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

need_cmd python3
need_cmd npm
need_cmd cargo
need_cmd rg

TARGET="${TARGET_OVERRIDE:-$(resolve_host_target)}"
SUFFIX="$(target_suffix "$TARGET")"
PYTHON_BIN="${PYTHON_BIN:-python3}"

prepare_signing_env

log "Repository root: $ROOT_DIR"
log "Target: $TARGET"
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
