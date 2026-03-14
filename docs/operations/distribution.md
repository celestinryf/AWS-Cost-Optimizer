# Distribution and Package Managers

This project ships cross-platform desktop installers via GitHub Releases.

## Current Release Targets

- macOS Apple Silicon (`aarch64-apple-darwin`)
- macOS Intel (`x86_64-apple-darwin`)
- Windows x64 (`x86_64-pc-windows-msvc`)
- Linux x64 (`x86_64-unknown-linux-gnu`)

Generated installer types:
- macOS: `.dmg`
- Windows: `.msi`, `.exe` (NSIS)
- Linux: `.deb`, `.AppImage`

## Package Manager Support

### macOS: Homebrew Cask

We generate a cask file from release assets:

```bash
bash scripts/update_homebrew_cask.sh --tag vX.Y.Z
```

Output:
- `packaging/homebrew/Casks/aws-cost-optimizer.rb`

To publish:
1. Copy that cask file into your Homebrew tap repo under `Casks/`.
2. Commit and push.
3. Users install with:

```bash
brew tap <owner>/<tap-repo>
brew install --cask aws-cost-optimizer
```

### Windows: WinGet

We generate WinGet manifests from release assets:

```bash
bash scripts/generate_winget_manifests.sh --tag vX.Y.Z
```

Output:
- `packaging/winget/<version>/...yaml`

To publish:
1. Fork `microsoft/winget-pkgs`.
2. Copy generated manifests to:
   `manifests/c/Celestinryf/AWSCostOptimizer/<version>/`
3. Open a PR to `winget-pkgs`.

### Linux

Linux binaries are distributed directly as `.deb` and `.AppImage` assets in GitHub Releases.

Example install from a downloaded `.deb`:

```bash
sudo apt install ./AWS\ Cost\ Optimizer_<version>_amd64.deb
```

## Release Workflow Automation

On each version tag release (`vX.Y.Z`):
- Build installers for all targets.
- Generate package-manager metadata files:
  - Homebrew cask
  - WinGet manifests
- Upload them as workflow artifacts:
  - `package-manager-manifests-vX.Y.Z`

Workflow file:
- `.github/workflows/release.yml`
