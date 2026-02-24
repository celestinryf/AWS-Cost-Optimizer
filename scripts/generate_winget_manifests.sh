#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

OWNER="celestinryf"
REPO="AWS-Cost-Optimizer"
TAG=""
PACKAGE_ID="Celestinryf.AWSCostOptimizer"
PUBLISHER="Celestinryf"
PACKAGE_NAME="AWS Cost Optimizer"
DESCRIPTION="Desktop workflow for identifying and executing S3 cost-saving actions"
MANIFEST_VERSION="1.10.0"
OUT_DIR_BASE="$ROOT_DIR/packaging/winget"

usage() {
  cat <<'EOF'
Generate WinGet manifest files from GitHub release assets.

Usage:
  ./scripts/generate_winget_manifests.sh --tag vX.Y.Z [options]

Options:
  --tag <tag>             Release tag (required), e.g. v0.2.0
  --owner <owner>         GitHub owner (default: celestinryf)
  --repo <repo>           GitHub repo (default: AWS-Cost-Optimizer)
  --package-id <id>       WinGet package identifier
  --publisher <name>      Publisher string
  --package-name <name>   Display package name
  --description <text>    Short description
  --out-dir <path>        Output base directory (default: packaging/winget)
  -h, --help              Show this help.
EOF
}

log() {
  printf '[winget] %s\n' "$*"
}

fail() {
  printf '[winget][error] %s\n' "$*" >&2
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
    --package-id)
      [[ $# -ge 2 ]] || fail "Missing value for --package-id"
      PACKAGE_ID="$2"
      shift 2
      ;;
    --publisher)
      [[ $# -ge 2 ]] || fail "Missing value for --publisher"
      PUBLISHER="$2"
      shift 2
      ;;
    --package-name)
      [[ $# -ge 2 ]] || fail "Missing value for --package-name"
      PACKAGE_NAME="$2"
      shift 2
      ;;
    --description)
      [[ $# -ge 2 ]] || fail "Missing value for --description"
      DESCRIPTION="$2"
      shift 2
      ;;
    --out-dir)
      [[ $# -ge 2 ]] || fail "Missing value for --out-dir"
      OUT_DIR_BASE="$2"
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

readarray -t MSI_ASSETS < <(
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

x64 = first(r"(x64|x86_64|amd64).*\.msi$")
arm64 = first(r"(aarch64|arm64).*\.msi$")

if not x64:
    print("Missing x64 MSI asset in release", file=sys.stderr)
    sys.exit(1)

print(x64)
print(arm64)
PY
)

X64_MSI="${MSI_ASSETS[0]}"
ARM64_MSI="${MSI_ASSETS[1]}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

gh release download "$TAG" --repo "$OWNER/$REPO" --pattern "$X64_MSI" --dir "$TMP_DIR" >/dev/null
X64_SHA="$(shasum -a 256 "$TMP_DIR/$X64_MSI" | awk '{print $1}')"
X64_URL_PATH="$(python3 - <<PY
import urllib.parse
print(urllib.parse.quote("$X64_MSI"))
PY
)"

ARM64_SHA=""
ARM64_URL_PATH=""
if [[ -n "$ARM64_MSI" ]]; then
  gh release download "$TAG" --repo "$OWNER/$REPO" --pattern "$ARM64_MSI" --dir "$TMP_DIR" >/dev/null
  ARM64_SHA="$(shasum -a 256 "$TMP_DIR/$ARM64_MSI" | awk '{print $1}')"
  ARM64_URL_PATH="$(python3 - <<PY
import urllib.parse
print(urllib.parse.quote("$ARM64_MSI"))
PY
)"
fi

VERSION="${TAG#v}"
OUT_DIR="$OUT_DIR_BASE/$VERSION"
mkdir -p "$OUT_DIR"

DEFAULT_LOCALE_FILE="$OUT_DIR/$PACKAGE_ID.locale.en-US.yaml"
INSTALLER_FILE="$OUT_DIR/$PACKAGE_ID.installer.yaml"
VERSION_FILE="$OUT_DIR/$PACKAGE_ID.yaml"

cat > "$VERSION_FILE" <<EOF
PackageIdentifier: $PACKAGE_ID
PackageVersion: $VERSION
DefaultLocale: en-US
ManifestType: version
ManifestVersion: $MANIFEST_VERSION
EOF

cat > "$DEFAULT_LOCALE_FILE" <<EOF
PackageIdentifier: $PACKAGE_ID
PackageVersion: $VERSION
PackageLocale: en-US
Publisher: $PUBLISHER
PublisherUrl: https://github.com/$OWNER
PackageName: $PACKAGE_NAME
PackageUrl: https://github.com/$OWNER/$REPO
License: MIT
ShortDescription: $DESCRIPTION
ManifestType: defaultLocale
ManifestVersion: $MANIFEST_VERSION
EOF

cat > "$INSTALLER_FILE" <<EOF
PackageIdentifier: $PACKAGE_ID
PackageVersion: $VERSION
InstallerType: wix
UpgradeBehavior: install
Installers:
  - Architecture: x64
    InstallerUrl: https://github.com/$OWNER/$REPO/releases/download/$TAG/$X64_URL_PATH
    InstallerSha256: $X64_SHA
EOF

if [[ -n "$ARM64_MSI" ]]; then
  cat >> "$INSTALLER_FILE" <<EOF
  - Architecture: arm64
    InstallerUrl: https://github.com/$OWNER/$REPO/releases/download/$TAG/$ARM64_URL_PATH
    InstallerSha256: $ARM64_SHA
EOF
fi

cat >> "$INSTALLER_FILE" <<EOF
ManifestType: installer
ManifestVersion: $MANIFEST_VERSION
EOF

log "Wrote WinGet manifests in: $OUT_DIR"
log "x64 MSI: $X64_MSI"
if [[ -n "$ARM64_MSI" ]]; then
  log "arm64 MSI: $ARM64_MSI"
else
  log "arm64 MSI: not found in release (x64-only manifest generated)"
fi
