#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RUN_ACTIONLINT=1
RUN_CLIENT_BUILD=1
RUN_SERVER_UNIT=0
RUN_DESKTOP_BUILD=0

usage() {
  cat <<'EOF'
Pre-push checklist for AWS-Cost-Optimizer.

Usage:
  ./scripts/prepush_check.sh [options]

Options:
  --full                Include server unit tests.
  --desktop-build       Run a local Tauri desktop build for your host target.
  --skip-actionlint     Skip workflow linting even if actionlint is installed.
  --skip-client-build   Skip `npm --prefix client run build`.
  -h, --help            Show this help.

Notes:
  - --desktop-build requires:
    - TAURI_SIGNING_PRIVATE_KEY_PASSWORD in your environment.
    - TAURI_SIGNING_PRIVATE_KEY in env OR key file at ~/.tauri/aws-cost-optimizer.key.
  - This script does not push or commit anything.
EOF
}

log() {
  printf '[prepush] %s\n' "$*"
}

warn() {
  printf '[prepush][warn] %s\n' "$*" >&2
}

fail() {
  printf '[prepush][error] %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
}

check_workflow_signing_refs() {
  local file
  for file in ".github/workflows/desktop.yml" ".github/workflows/release.yml"; do
    rg -q 'TAURI_SIGNING_PRIVATE_KEY' "$file" \
      || fail "$file is missing TAURI_SIGNING_PRIVATE_KEY reference."
    rg -q 'TAURI_SIGNING_PRIVATE_KEY_PASSWORD' "$file" \
      || fail "$file is missing TAURI_SIGNING_PRIVATE_KEY_PASSWORD reference."
  done
  log "Workflow signing secret references look correct."
}

run_actionlint() {
  if [[ "$RUN_ACTIONLINT" -eq 0 ]]; then
    return
  fi
  if command -v actionlint >/dev/null 2>&1; then
    log "Running actionlint..."
    actionlint -color
  else
    warn "actionlint not installed; skipping workflow lint."
    warn "Install: https://github.com/rhysd/actionlint"
  fi
}

run_client_build() {
  if [[ "$RUN_CLIENT_BUILD" -eq 0 ]]; then
    return
  fi
  need_cmd npm
  if [[ ! -d "$ROOT_DIR/client/node_modules" ]]; then
    log "client/node_modules missing; running npm ci..."
    npm --prefix "$ROOT_DIR/client" ci
  fi
  log "Running client build (tsc + vite)..."
  npm --prefix "$ROOT_DIR/client" run build
}

run_server_unit_tests() {
  if [[ "$RUN_SERVER_UNIT" -eq 0 ]]; then
    return
  fi
  need_cmd make
  log "Running server unit tests..."
  make -C "$ROOT_DIR/server" test-unit
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

prepare_signing_env() {
  if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    local key_path="${TAURI_KEY_PATH:-$HOME/.tauri/aws-cost-optimizer.key}"
    [[ -f "$key_path" ]] || fail "Set TAURI_SIGNING_PRIVATE_KEY or create key at $key_path"
    TAURI_SIGNING_PRIVATE_KEY="$(cat "$key_path")"
    export TAURI_SIGNING_PRIVATE_KEY
    log "Loaded TAURI_SIGNING_PRIVATE_KEY from $key_path"
  fi

  [[ -n "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" ]] \
    || fail "Set TAURI_SIGNING_PRIVATE_KEY_PASSWORD before --desktop-build."
}

run_desktop_build() {
  if [[ "$RUN_DESKTOP_BUILD" -eq 0 ]]; then
    return
  fi
  need_cmd npm
  need_cmd cargo
  prepare_signing_env
  local target
  target="$(resolve_host_target)"
  if [[ ! -d "$ROOT_DIR/client/node_modules" ]]; then
    log "client/node_modules missing; running npm ci..."
    npm --prefix "$ROOT_DIR/client" ci
  fi
  log "Running local Tauri desktop build for target $target..."
  npm --prefix "$ROOT_DIR/client" run tauri -- build --target "$target"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full)
      RUN_SERVER_UNIT=1
      shift
      ;;
    --desktop-build)
      RUN_DESKTOP_BUILD=1
      shift
      ;;
    --skip-actionlint)
      RUN_ACTIONLINT=0
      shift
      ;;
    --skip-client-build)
      RUN_CLIENT_BUILD=0
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

cd "$ROOT_DIR"
need_cmd rg

log "Repository root: $ROOT_DIR"
check_workflow_signing_refs
run_actionlint
run_client_build
run_server_unit_tests
run_desktop_build
log "All selected checks passed."
