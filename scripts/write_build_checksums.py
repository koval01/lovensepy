#!/usr/bin/env python3
"""Write SHA256SUMS (GNU sha256sum -c compatible) for build outputs.

Usage:
  python scripts/write_build_checksums.py dist-nuitka
      All regular files under the directory (except SHA256SUMS), sorted by path.

  python scripts/write_build_checksums.py --release-assets artifacts
      Only *.dmg and *.exe anywhere under the tree; lines use basename only so
      users can verify after downloading release assets into one folder.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys


def _sha256_file(path: pathlib.Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default="dist-nuitka",
        help="Directory to scan (default: dist-nuitka)",
    )
    parser.add_argument(
        "--release-assets",
        action="store_true",
        help="Only .dmg/.exe; use basename in output (for GitHub Release attachments)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        help="Output file (default: ROOT/SHA256SUMS)",
    )
    args = parser.parse_args()
    root = pathlib.Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    out = (args.output or (root / "SHA256SUMS")).resolve()
    if out == root:
        print("Refusing to use root as output path.", file=sys.stderr)
        return 1

    entries: list[tuple[str, str]] = []
    if args.release_assets:
        candidates = [
            p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".dmg", ".exe")
        ]
        names = [p.name for p in candidates]
        if len(names) != len(set(names)):
            dup = {n for n in names if names.count(n) > 1}
            print(f"Duplicate basenames under {root}: {dup}", file=sys.stderr)
            return 1
        entries = sorted(((_sha256_file(p), p.name) for p in candidates), key=lambda x: x[1])
    else:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.name == "SHA256SUMS":
                continue
            if p.resolve() == out:
                continue
            rel = p.relative_to(root).as_posix()
            entries.append((_sha256_file(p), rel))

    lines = [f"{digest}  {name}\n" for digest, name in entries]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(lines), encoding="utf-8", newline="\n")
    print(f"Wrote {len(lines)} entries to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
