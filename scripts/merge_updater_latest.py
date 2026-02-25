#!/usr/bin/env python3
"""Collect and merge Tauri updater metadata into a canonical latest.json."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote


def _error(msg: str) -> None:
    print(f"[merge-updater][error] {msg}", file=sys.stderr)


def _platform_keys(asset_name: str) -> list[str]:
    name = asset_name.lower()
    keys: list[str] = []

    is_arm64 = bool(re.search(r"(aarch64|arm64)", name))
    is_x64 = bool(re.search(r"(x86_64|x64|amd64)", name))

    if name.endswith(".app.tar.gz"):
        if is_arm64:
            keys.extend(["darwin-aarch64", "darwin-aarch64-app"])
        elif is_x64:
            keys.extend(["darwin-x86_64", "darwin-x86_64-app"])
    elif name.endswith(".appimage"):
        keys.append("linux-x86_64")
        keys.append("linux-x86_64-appimage")
    elif name.endswith(".deb"):
        keys.append("linux-x86_64-deb")
    elif name.endswith(".rpm"):
        keys.append("linux-x86_64-rpm")
    elif name.endswith(".msi"):
        keys.append("windows-x86_64")
        keys.append("windows-x86_64-msi")
    elif name.endswith("-setup.exe"):
        keys.append("windows-x86_64-nsis")
    elif name.endswith(".exe") and "setup" in name:
        keys.append("windows-x86_64-nsis")

    return keys


def _read_release_notes(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _collect(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir)
    if not bundle_dir.exists():
        _error(f"Bundle directory does not exist: {bundle_dir}")
        return 1

    platforms: dict[str, dict[str, str]] = {}
    sig_paths = sorted(bundle_dir.rglob("*.sig"))
    if not sig_paths:
        _error(f"No .sig files found under {bundle_dir}")
        return 1

    for sig_path in sig_paths:
        asset_path = Path(str(sig_path)[:-4])
        if not asset_path.exists():
            continue
        asset_name = asset_path.name
        keys = _platform_keys(asset_name)
        if not keys:
            continue

        signature = sig_path.read_text(encoding="utf-8").strip()
        if not signature:
            _error(f"Empty signature in {sig_path}")
            return 1

        asset_url = (
            f"https://github.com/{args.repo}/releases/download/"
            f"{args.tag}/{quote(asset_name)}"
        )

        for key in keys:
            value = {"signature": signature, "url": asset_url}
            if key in platforms and platforms[key] != value:
                _error(f"Conflicting platform payload for key '{key}'")
                return 1
            platforms[key] = value

    if not platforms:
        _error("No updater platforms were collected from signatures")
        return 1

    payload = {
        "tag": args.tag,
        "version": args.version,
        "notes": _read_release_notes(Path(args.notes_file)),
        "pub_date": dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "platforms": {k: platforms[k] for k in sorted(platforms)},
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[merge-updater] Wrote updater fragment: {output}")
    return 0


def _merge(args: argparse.Namespace) -> int:
    files = sorted(glob.glob(args.input_glob, recursive=True))
    if not files:
        _error(f"No updater fragment files found for glob: {args.input_glob}")
        return 1

    version: str | None = None
    tag: str | None = None
    notes: str | None = None
    pub_date: str | None = None
    merged_platforms: dict[str, dict[str, str]] = {}

    for file_path in files:
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        file_version = data.get("version")
        file_tag = data.get("tag")
        file_notes = data.get("notes")
        file_pub_date = data.get("pub_date")
        platforms = data.get("platforms", {})

        if (
            not file_version
            or not file_tag
            or not isinstance(platforms, dict)
        ):
            _error(f"Invalid updater fragment format: {file_path}")
            return 1

        if version is None:
            version = file_version
            tag = file_tag
            notes = file_notes or ""
            pub_date = file_pub_date or ""
        elif file_version != version:
            _error(f"Mismatched versions in fragments: {file_path}")
            return 1
        elif file_tag != tag:
            _error(f"Mismatched tags in fragments: {file_path}")
            return 1
        elif (file_notes or "") != (notes or ""):
            _error(f"Mismatched release notes in fragments: {file_path}")
            return 1

        for key, value in platforms.items():
            if (
                not isinstance(value, dict)
                or "signature" not in value
                or "url" not in value
            ):
                _error(f"Invalid platform payload in {file_path} for key '{key}'")
                return 1
            if key in merged_platforms and merged_platforms[key] != value:
                _error(f"Conflicting platform entry for '{key}' across fragments")
                return 1
            merged_platforms[key] = value

    if version is None:
        _error("No valid updater fragments loaded")
        return 1

    merged = {
        "version": version,
        "notes": notes or "",
        "pub_date": pub_date
        or dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "platforms": {k: merged_platforms[k] for k in sorted(merged_platforms)},
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    print(f"[merge-updater] Wrote merged latest.json: {output}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser(
        "collect", help="Collect updater metadata from build bundle artifacts."
    )
    collect.add_argument("--bundle-dir", required=True)
    collect.add_argument("--repo", required=True)
    collect.add_argument("--tag", required=True)
    collect.add_argument("--version", required=True)
    collect.add_argument("--notes-file", required=True)
    collect.add_argument("--output", required=True)
    collect.set_defaults(func=_collect)

    merge = subparsers.add_parser(
        "merge", help="Merge updater fragment files into latest.json."
    )
    merge.add_argument("--input-glob", required=True)
    merge.add_argument("--output", required=True)
    merge.set_defaults(func=_merge)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
