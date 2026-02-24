# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the AWS Cost Optimizer API sidecar binary.

Build command (run from server/):
    pyinstaller aws-cost-optimizer-api.spec

Output: dist/aws-cost-optimizer-api  (or dist/aws-cost-optimizer-api.exe on Windows)

The produced binary is placed into client/src-tauri/binaries/ with a
target-triple suffix so Tauri can bundle it as a sidecar:
    macOS arm64:  aws-cost-optimizer-api-aarch64-apple-darwin
    macOS x86_64: aws-cost-optimizer-api-x86_64-apple-darwin
    Windows:      aws-cost-optimizer-api-x86_64-pc-windows-msvc.exe
    Linux x86_64: aws-cost-optimizer-api-x86_64-unknown-linux-gnu
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules  # noqa: F821

HERE = Path(SPECPATH)  # noqa: F821  (PyInstaller provides SPECPATH)

# botocore bundles its endpoint data as package data; PyInstaller's static
# analysis misses it, so we collect it explicitly.
_extra_datas = (
    collect_data_files("botocore")
    + collect_data_files("boto3")
)
_extra_hiddenimports = collect_submodules("app")

a = Analysis(
    [str(HERE / "bundle_entry.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=[
        *_extra_datas,
    ],
    hiddenimports=[
        *_extra_hiddenimports,
        # uvicorn internals not caught by static analysis
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # starlette / fastapi internals
        "starlette.middleware.cors",
        # pydantic v2
        "pydantic.deprecated.config",
        "pydantic.deprecated.class_validators",
        # email-validator (pydantic optional dep - suppress import warnings)
        "email_validator",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aws-cost-optimizer-api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=sys.platform == "linux",  # Show console on Linux only
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
