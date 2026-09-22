"""Checksummed local backup and fail-closed restore for private Kroika data."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
from typing import Any
from uuid import uuid4


BACKUP_FORMAT = "kroika-local-backup/v1"
_IMAGE_NAME = re.compile(r"img_[a-f0-9]{32}\.(?:jpg|png|webp)")


class BackupError(RuntimeError):
    """Raised when a backup cannot be proven complete and safe to use."""


def _private(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        # Windows protects these files through ACLs, not POSIX mode bits.
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_check(path: Path) -> int:
    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True
        )
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise BackupError("Проверка целостности резервной базы данных не пройдена.")
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise BackupError("Резервная база данных не открывается.") from exc


def _manifest_entry(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {"path": relative, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def create_backup(database_path: Path, image_root: Path, destination: Path) -> dict[str, Any]:
    """Create a consistent SQLite snapshot plus images and a checksum manifest."""

    database_path = database_path.resolve()
    image_root = image_root.resolve()
    destination = destination.resolve()
    if not database_path.is_file():
        raise BackupError("База данных Kroika не найдена.")
    if image_root.exists() and not image_root.is_dir():
        raise BackupError("Путь хранилища изображений не является каталогом.")
    if destination.exists():
        raise BackupError("Каталог резервной копии уже существует.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = Path(tempfile.mkdtemp(prefix=".kroika-backup-", dir=destination.parent))
    _private(temporary, 0o700)
    try:
        backup_database = temporary / "kroika.db"
        source = sqlite3.connect(database_path)
        target = sqlite3.connect(backup_database)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        _private(backup_database, 0o600)
        schema_version = _database_check(backup_database)

        backup_images = temporary / "images"
        backup_images.mkdir(mode=0o700)
        if image_root.is_dir():
            for image in sorted(image_root.iterdir()):
                if image.is_symlink() or not image.is_file() or not _IMAGE_NAME.fullmatch(image.name):
                    continue
                copied = backup_images / image.name
                shutil.copyfile(image, copied)
                _private(copied, 0o600)

        data_files = [backup_database, *sorted(backup_images.iterdir())]
        manifest = {
            "format": BACKUP_FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "database_schema_version": schema_version,
            "files": [_manifest_entry(temporary, path) for path in data_files],
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _private(manifest_path, 0o600)
        temporary.replace(destination)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _safe_manifest_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise BackupError("Манифест содержит небезопасный путь.")
    if value == "kroika.db":
        return path
    if len(path.parts) == 2 and path.parts[0] == "images" and _IMAGE_NAME.fullmatch(path.name):
        return path
    raise BackupError("Манифест содержит неподдерживаемый файл.")


def verify_backup(backup_root: Path) -> dict[str, Any]:
    """Verify format, exact file set, hashes and SQLite integrity before restore."""

    backup_root = backup_root.resolve()
    manifest_path = backup_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("Манифест резервной копии отсутствует или повреждён.") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
        raise BackupError("Формат резервной копии не поддерживается.")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise BackupError("В манифесте нет списка файлов.")

    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise BackupError("Запись файла в манифесте повреждена.")
        relative = _safe_manifest_path(str(entry.get("path", "")))
        if relative.as_posix() in expected:
            raise BackupError("Манифест содержит повторяющийся файл.")
        expected.add(relative.as_posix())
        path = backup_root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise BackupError(f"Файл резервной копии отсутствует: {relative.as_posix()}.")
        if path.stat().st_size != entry.get("size_bytes") or _sha256(path) != entry.get("sha256"):
            raise BackupError(f"Контрольная сумма не совпала: {relative.as_posix()}.")

    actual = {
        path.relative_to(backup_root).as_posix()
        for path in backup_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != expected:
        raise BackupError("Состав резервной копии не совпадает с манифестом.")
    if "kroika.db" not in expected:
        raise BackupError("В резервной копии нет базы данных.")
    schema_version = _database_check(backup_root / "kroika.db")
    if schema_version != manifest.get("database_schema_version"):
        raise BackupError("Версия схемы базы не совпадает с манифестом.")
    return manifest


def restore_backup(
    backup_root: Path,
    database_path: Path,
    image_root: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Restore a verified copy; existing data requires explicit overwrite."""

    manifest = verify_backup(backup_root)
    backup_root = backup_root.resolve()
    database_path = database_path.resolve()
    image_root = image_root.resolve()
    if image_root.exists() and not image_root.is_dir():
        raise BackupError("Целевой путь изображений не является каталогом.")
    images_exist = image_root.is_dir() and any(image_root.iterdir())
    if (database_path.exists() or images_exist) and not overwrite:
        raise BackupError("Целевое хранилище не пусто; восстановление остановлено.")

    database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    image_root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    database_part = database_path.with_name(f".{database_path.name}.restore-{uuid4().hex}")
    image_part = Path(tempfile.mkdtemp(prefix=".kroika-images-restore-", dir=image_root.parent))
    old_database: Path | None = None
    old_images: Path | None = None
    try:
        shutil.copyfile(backup_root / "kroika.db", database_part)
        _private(database_part, 0o600)
        _database_check(database_part)
        for image in sorted((backup_root / "images").iterdir()):
            copied = image_part / image.name
            shutil.copyfile(image, copied)
            _private(copied, 0o600)
        _private(image_part, 0o700)
        if database_path.exists():
            old_database = database_path.with_name(
                f".{database_path.name}.pre-restore-{uuid4().hex}"
            )
            database_path.replace(old_database)
        if image_root.exists():
            old_images = image_root.with_name(f".{image_root.name}.pre-restore-{uuid4().hex}")
            image_root.replace(old_images)
        database_part.replace(database_path)
        _private(database_path, 0o600)
        image_part.replace(image_root)
        _private(image_root, 0o700)
        if old_database is not None:
            try:
                old_database.unlink()
            except OSError:
                pass
        if old_images is not None:
            shutil.rmtree(old_images, ignore_errors=True)
        return manifest
    except Exception:
        database_part.unlink(missing_ok=True)
        shutil.rmtree(image_part, ignore_errors=True)
        if old_database is not None and old_database.exists():
            database_path.unlink(missing_ok=True)
            old_database.replace(database_path)
        elif old_database is None:
            database_path.unlink(missing_ok=True)
        if old_images is not None and old_images.exists():
            if image_root.exists():
                shutil.rmtree(image_root)
            old_images.replace(image_root)
        raise
