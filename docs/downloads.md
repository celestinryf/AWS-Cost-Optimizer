# Download Builds

Use GitHub Releases for all installable builds.

Release page:
- https://github.com/celestinryf/AWS-Cost-Optimizer/releases

Latest release:
- https://github.com/celestinryf/AWS-Cost-Optimizer/releases/latest

## List available versions

Browser:
- Open the Releases page and pick a version tag (for example `v0.2.0`).

CLI:

```bash
gh release list --repo celestinryf/AWS-Cost-Optimizer
```

## Download by platform (CLI)

Replace `vX.Y.Z` with a real release tag.

### macOS (Apple Silicon + Intel)

```bash
gh release download vX.Y.Z --repo celestinryf/AWS-Cost-Optimizer --pattern "*.dmg"
```

### Windows

MSI:

```bash
gh release download vX.Y.Z --repo celestinryf/AWS-Cost-Optimizer --pattern "*.msi"
```

NSIS EXE:

```bash
gh release download vX.Y.Z --repo celestinryf/AWS-Cost-Optimizer --pattern "*.exe"
```

### Linux

Debian package:

```bash
gh release download vX.Y.Z --repo celestinryf/AWS-Cost-Optimizer --pattern "*.deb"
```

AppImage:

```bash
gh release download vX.Y.Z --repo celestinryf/AWS-Cost-Optimizer --pattern "*.AppImage"
```

## Direct versioned link templates

Use these when you already know the exact asset filename.

```text
https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/<asset-filename>
```

Examples:

```text
https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/AWS%20Cost%20Optimizer_0.1.0_aarch64.dmg
https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/AWS%20Cost%20Optimizer_0.1.0_x64_en-US.msi
https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/aws-cost-optimizer_0.1.0_amd64.AppImage
```

## Homebrew and WinGet

For package manager distribution flow, see:
- `docs/distribution.md`
