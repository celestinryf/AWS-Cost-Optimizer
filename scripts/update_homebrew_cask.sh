#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

OWNER="celestinryf"
REPO="AWS-Cost-Optimizer"
TAG=""
OUT_FILE="$ROOT_DIR/packaging/homebrew/Casks/aws-cost-optimizer.rb"

usage() {
  cat <<'EOF'
Generate a Homebrew Cask file from GitHub release assets.

Usage:
  ./scripts/update_homebrew_cask.sh --tag vX.Y.Z [options]

Options:
  --tag <tag>           Release tag (required), e.g. v0.2.0
  --owner <owner>       GitHub owner (default: celestinryf)
  --repo <repo>         GitHub repo (default: AWS-Cost-Optimizer)
  --out <path>          Output cask file path
  -h, --help            Show this help.
EOF
}

log() {
  printf '[homebrew-cask] %s\n' "$*"
}

fail() {
  printf '[homebrew-cask][error] %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      [[ $# -ge 2 ]] || fail "Missing value for --tag"
      TAG="$2"
      shift 2
      ;;
    --owner)
      [[ $# -ge 2 ]] || fail "Missing value for --owner"
      OWNER="$2"
      shift 2
      ;;
    --repo)
      [[ $# -ge 2 ]] || fail "Missing value for --repo"
      REPO="$2"
      shift 2
      ;;
    --out)
      [[ $# -ge 2 ]] || fail "Missing value for --out"
      OUT_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

[[ -n "$TAG" ]] || fail "Missing required --tag (e.g., --tag v0.2.0)"

need_cmd gh
need_cmd python3
need_cmd shasum

RELEASE_JSON="$(gh release view "$TAG" --repo "$OWNER/$REPO" --json assets)"

readarray -t DMG_ASSETS < <(
  RELEASE_JSON="$RELEASE_JSON" python3 - <<'PY'
import json
import os
import re
import sys

assets = [a["name"] for a in json.loads(os.environ["RELEASE_JSON"])["assets"]]

def first(pattern):
    rx = re.compile(pattern, re.IGNORECASE)
    for name in assets:
        if rx.search(name):
            return name
    return ""

arm = first(r"(aarch64|arm64).*\.dmg$")
intel = first(r"(x64|x86_64|amd64).*\.dmg$")

if not arm:
    print("Missing arm64/aarch64 macOS dmg asset", file=sys.stderr)
    sys.exit(1)
if not intel:
    print("Missing intel/x86_64 macOS dmg asset", file=sys.stderr)
    sys.exit(1)

print(arm)
print(intel)
PY
)

ARM_DMG="${DMG_ASSETS[0]}"
INTEL_DMG="${DMG_ASSETS[1]}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

gh release download "$TAG" --repo "$OWNER/$REPO" --pattern "$ARM_DMG" --dir "$TMP_DIR" >/dev/null
gh release download "$TAG" --repo "$OWNER/$REPO" --pattern "$INTEL_DMG" --dir "$TMP_DIR" >/dev/null

ARM_SHA="$(shasum -a 256 "$TMP_DIR/$ARM_DMG" | awk '{print $1}')"
INTEL_SHA="$(shasum -a 256 "$TMP_DIR/$INTEL_DMG" | awk '{print $1}')"

ARM_URL_PATH="$(python3 - <<PY
import urllib.parse
print(urllib.parse.quote("$ARM_DMG"))
PY
)"
INTEL_URL_PATH="$(python3 - <<PY
import urllib.parse
print(urllib.parse.quote("$INTEL_DMG"))
PY
)"

VERSION="${TAG#v}"
mkdir -p "$(dirname "$OUT_FILE")"

cat > "$OUT_FILE" <<EOF
cask "aws-cost-optimizer" do
  version "$VERSION"

  if Hardware::CPU.arm?
    sha256 "$ARM_SHA"
    url "https://github.com/$OWNER/$REPO/releases/download/$TAG/$ARM_URL_PATH"
  else
    sha256 "$INTEL_SHA"
    url "https://github.com/$OWNER/$REPO/releases/download/$TAG/$INTEL_URL_PATH"
  end

  name "AWS Cost Optimizer"
  desc "Desktop workflow for identifying and executing S3 cost-saving actions"
  homepage "https://github.com/$OWNER/$REPO"

  auto_updates true
  app "AWS Cost Optimizer.app"
end
EOF

log "Wrote Homebrew cask: $OUT_FILE"
log "arm64 dmg: $ARM_DMG"
log "x64 dmg: $INTEL_DMG"
