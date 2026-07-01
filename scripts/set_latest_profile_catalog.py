#!/usr/bin/env python3
"""Create a stable latest profile catalog path.

The profile script writes timestamped directories and ZIPs for reproducibility. This
helper creates stable aliases for dashboard users:

    outputs/trinetx_profile/latest.zip
    outputs/trinetx_profile/latest/

It does not inspect raw TriNetX data.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create stable latest aliases for TriNetX profile outputs.")
    p.add_argument("--profile-dir", default="outputs/trinetx_profile")
    p.add_argument("--source", default=None, help="Optional specific timestamped profile directory or ZIP.")
    return p.parse_args()


def newest_candidate(profile_dir: Path) -> Path | None:
    if not profile_dir.exists():
        return None
    candidates = []
    for p in profile_dir.iterdir():
        if p.name in {"latest", "latest.zip"}:
            continue
        if p.is_dir() or (p.is_file() and p.suffix.lower() == ".zip"):
            candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    args = parse_args()
    profile_dir = Path(args.profile_dir)
    src = Path(args.source) if args.source else newest_candidate(profile_dir)
    if src is None or not src.exists():
        print(f"No profile output found under {profile_dir}", file=sys.stderr)
        return 2

    profile_dir.mkdir(parents=True, exist_ok=True)
    latest_zip = profile_dir / "latest.zip"
    latest_dir = profile_dir / "latest"

    if src.is_file() and src.suffix.lower() == ".zip":
        shutil.copy2(src, latest_zip)
        print(f"Updated {latest_zip} from {src}")
    elif src.is_dir():
        copy_dir(src, latest_dir)
        zip_src = src.with_suffix(".zip")
        if zip_src.exists():
            shutil.copy2(zip_src, latest_zip)
            print(f"Updated {latest_zip} from {zip_src}")
        print(f"Updated {latest_dir} from {src}")
    else:
        print(f"Unsupported profile source: {src}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
