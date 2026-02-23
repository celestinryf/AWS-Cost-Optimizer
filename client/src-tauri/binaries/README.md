# Sidecar Binaries

Place the PyInstaller-built FastAPI server binary here before running `tauri dev` or `tauri build`.
The filename must include the Rust target triple for the current machine.

Build the binary:
```bash
cd ../../server
pip install -r requirements-bundle.txt
pyinstaller aws-cost-optimizer-api.spec
```

Then copy with the correct target triple:
```bash
# macOS Apple Silicon (M1/M2/M3):
cp ../../server/dist/aws-cost-optimizer-api \
   aws-cost-optimizer-api-aarch64-apple-darwin

# macOS Intel:
cp ../../server/dist/aws-cost-optimizer-api \
   aws-cost-optimizer-api-x86_64-apple-darwin

# Windows:
cp ../../server/dist/aws-cost-optimizer-api.exe \
   aws-cost-optimizer-api-x86_64-pc-windows-msvc.exe

# Linux x86_64:
cp ../../server/dist/aws-cost-optimizer-api \
   aws-cost-optimizer-api-x86_64-unknown-linux-gnu
```

Get the exact triple for your machine:
```bash
rustc -vV | grep host
```
