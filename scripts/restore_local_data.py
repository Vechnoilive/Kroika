#!/usr/bin/env python3
"""Verify and restore a local Kroika backup."""

from __future__ import annotations

import argparse
from pathlib import Path

from kroika_backend.backup import BackupError, create_backup, restore_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Восстановить резервную копию Kroika")
    parser.add_argument("backup", type=Path, help="каталог проверенной резервной копии")
    parser.add_argument("--database", type=Path, default=Path("data/kroika.db"))
    parser.add_argument("--images", type=Path, default=Path("data/images"))
    parser.add_argument(
        "--replace",
        action="store_true",
        help="заменить существующие данные; требует --safety-backup",
    )
    parser.add_argument(
        "--safety-backup",
        type=Path,
        help="новый каталог для обязательной копии данных перед заменой",
    )
    args = parser.parse_args()
    if args.replace and args.safety_backup is None:
        parser.error("Для --replace обязательно укажите --safety-backup.")
    try:
        if args.replace:
            assert args.safety_backup is not None
            images_exist = args.images.is_dir() and any(args.images.iterdir())
            if args.database.exists():
                create_backup(args.database, args.images, args.safety_backup)
            elif images_exist:
                raise BackupError(
                    "Найдены изображения без рабочей базы; автоматическая страховочная "
                    "копия невозможна. Сначала сохраните каталог вручную."
                )
        manifest = restore_backup(
            args.backup, args.database, args.images, overwrite=args.replace
        )
    except BackupError as exc:
        parser.error(str(exc))
    print(
        f"Данные восстановлены и проверены. Версия схемы: "
        f"{manifest['database_schema_version']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
