#!/usr/bin/env bash

desktop_common_need_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || {
    printf '[desktop-common][error] Missing required command: %s\n' "$cmd" >&2
    return 1
  }
}

desktop_common_resolve_host_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
    Darwin)
      case "$arch" in
        arm64|aarch64) echo "aarch64-apple-darwin" ;;
        x86_64) echo "x86_64-apple-darwin" ;;
        *)
          printf '[desktop-common][error] Unsupported macOS architecture: %s\n' "$arch" >&2
          return 1
          ;;
      esac
      ;;
    Linux)
      case "$arch" in
        x86_64|amd64) echo "x86_64-unknown-linux-gnu" ;;
        aarch64|arm64) echo "aarch64-unknown-linux-gnu" ;;
        *)
          printf '[desktop-common][error] Unsupported Linux architecture: %s\n' "$arch" >&2
          return 1
          ;;
      esac
      ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      echo "x86_64-pc-windows-msvc"
      ;;
    *)
      printf '[desktop-common][error] Unsupported OS for desktop build: %s\n' "$os" >&2
      return 1
      ;;
  esac
}

desktop_common_target_suffix() {
  local target="$1"
  case "$target" in
    *windows*) echo ".exe" ;;
    *) echo "" ;;
  esac
}

desktop_common_load_signing_key() {
  local key_path="${1:-$HOME/.tauri/aws-cost-optimizer.key}"
  if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    [[ -f "$key_path" ]] || {
      printf '[desktop-common][error] Missing key file: %s (or set TAURI_SIGNING_PRIVATE_KEY).\n' "$key_path" >&2
      return 1
    }
    TAURI_SIGNING_PRIVATE_KEY="$(cat "$key_path")"
    export TAURI_SIGNING_PRIVATE_KEY
  fi
}
