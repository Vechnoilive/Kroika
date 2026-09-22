#!/usr/bin/env python3
"""Create a private checksummed backup of local Kroika data."""

from __future__ import annotations

import argparse
from pathlib import Path

from kroika_backend.backup import BackupError, create_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Создать резервную копию Kroika")
    parser.add_argument("destination", type=Path, help="новый каталог резервной копии")
    parser.add_argument("--database", type=Path, default=Path("data/kroika.db"))
    parser.add_argument("--images", type=Path, default=Path("data/images"))
    args = parser.parse_args()
    try:
        manifest = create_backup(args.database, args.images, args.destination)
    except BackupError as exc:
        parser.error(str(exc))
    print(
        f"Резервная копия проверена: {args.destination} "
        f"({len(manifest['files'])} файлов)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
