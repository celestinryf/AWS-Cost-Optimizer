# Pre-Push Checklist

Use this script before pushing CI or release workflow changes:

```bash
./scripts/prepush_check.sh
```

## Common modes

Quick checks (workflow refs + optional actionlint + client build):

```bash
./scripts/prepush_check.sh
```

Include server unit tests:

```bash
./scripts/prepush_check.sh --full
```

Run a local desktop build with updater signing:

```bash
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD='your-password'
./scripts/prepush_check.sh --desktop-build
```

If `TAURI_SIGNING_PRIVATE_KEY` is not set, the script loads it from:

```text
~/.tauri/aws-cost-optimizer.key
```

## Optional Git hook

To run the checklist automatically on `git push`:

```bash
ln -sf ../../scripts/prepush_check.sh .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```
