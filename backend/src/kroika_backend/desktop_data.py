"""Checked, additive migration of SQLite records and their images."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from uuid import uuid4

from .backup import BackupError, create_backup, verify_backup, _sha256
from .repository import SQLiteRepository


TABLE_KEYS = {
    "projects": ("project_id",), "measurement_profiles": ("profile_id",),
    "generations": ("generation_id",), "project_revisions": ("project_id", "revision"),
    "physical_validation_records": ("record_id",),
    "generation_input_snapshots": ("generation_id",),
}


def import_data(source: Path, repository: SQLiteRepository, images: Path, backups: Path) -> dict:
    source = source.resolve()
    if not (source / "kroika.db").is_file() and (source / "data" / "kroika.db").is_file():
        source = source / "data"
    source_database = source / "kroika.db"
    if source_database == repository.database_path.resolve():
        raise BackupError("Эта папка уже используется приложением.")
    backup = backups / f"import-{uuid4().hex}"
    create_backup(source_database, source / "images", backup)
    verify_backup(backup)
    copied = []
    committed = False
    try:
        source_repository = SQLiteRepository(backup / "kroika.db")
        with sqlite3.connect(source_repository.database_path) as database:
            tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"projects", "generations", "measurement_profiles"} <= tables:
                raise BackupError("В выбранной папке нет базы проектов Кройки.")
        try:
            source_repository.initialize()
        except RuntimeError as error:
            raise BackupError("Версия исходной базы не поддерживается этой Кройкой.") from error
        refs = set()
        for project in source_repository.list_projects():
            refs.update(source_repository.project_image_refs(project["project_id"]))
        available = {path.stem for path in (backup / "images").iterdir()}
        if refs - available:
            raise BackupError("В исходной папке не хватает фотографий проектов. Импорт остановлен.")
        rows = {}
        with sqlite3.connect(source_repository.database_path) as database:
            database.row_factory = sqlite3.Row
            if database.execute("PRAGMA foreign_key_check").fetchone():
                raise BackupError("Связи исходной базы повреждены.")
            for table in TABLE_KEYS:
                rows[table] = [dict(row) for row in database.execute(f"SELECT * FROM {table}")]  # nosec B608 # TABLE_KEYS is a fixed allowlist
        retained = backups / f"source-{uuid4().hex}"
        create_backup(source_repository.database_path, backup / "images", retained)
        images.mkdir(parents=True, exist_ok=True)
        report = {table: 0 for table in TABLE_KEYS}
        report.update(images=0, skipped=0)
        for image in (backup / "images").iterdir():
            destination = images / image.name
            if destination.exists():
                if destination.is_symlink() or _sha256(destination) != _sha256(image):
                    raise BackupError("Есть разные фотографии с одинаковыми ID. Импорт остановлен.")
            else:
                descriptor, temporary_name = tempfile.mkstemp(prefix=".import-image-", dir=images)
                temporary_image = Path(temporary_name)
                try:
                    with os.fdopen(descriptor, "wb") as output, image.open("rb") as input_stream:
                        shutil.copyfileobj(input_stream, output)
                        output.flush()
                        os.fsync(output.fileno())
                    if os.name == "nt":
                        # Windows rename fails if the destination already exists.
                        os.rename(temporary_image, destination)
                    else:
                        os.link(temporary_image, destination)
                    copied.append(destination)
                finally:
                    temporary_image.unlink(missing_ok=True)
                report["images"] += 1
        with repository._connect() as target:
            target.execute("BEGIN IMMEDIATE")
            pending = []
            for table, entries in rows.items():
                keys = TABLE_KEYS[table]
                for row in entries:
                    values = {key: value for key, value in row.items() if key != "sequence"}
                    existing = target.execute(
                        f"SELECT * FROM {table} WHERE " + " AND ".join(f"{key}=?" for key in keys),  # nosec B608 # table and keys come from TABLE_KEYS
                        tuple(row[key] for key in keys),
                    ).fetchone()
                    if existing:
                        matches = all(
                            (json.loads(existing[key]) == json.loads(value) if key == "payload"
                             else existing[key] == value) for key, value in values.items()
                        )
                        if not matches:
                            raise BackupError(
                                "Есть записи с одинаковыми ID и разными данными. "
                                "Существующие проекты не изменены."
                            )
                        report["skipped"] += 1
                    else:
                        pending.append((table, values))
            for table, values in pending:
                columns = ",".join('"' + key.replace('"', '""') + '"' for key in values)
                target.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in values)})",  # nosec B608 # fixed table; quoted columns; bound values
                    tuple(values.values()),
                )
                report[table] += 1
            if target.execute("PRAGMA foreign_key_check").fetchone():
                raise BackupError("После импорта нарушены связи записей; изменения отменены.")
        committed = True
        return {**report, "backup_dir": str(retained)}
    except (sqlite3.Error, OSError, ValueError) as error:
        raise BackupError("Не удалось импортировать данные. Проверьте исходную папку и доступ к файлам.") from error
    finally:
        if not committed:
            for path in copied:
                path.unlink(missing_ok=True)
        shutil.rmtree(backup, ignore_errors=True)


def migrate_legacy(source_root: Path, data_dir: Path, home: Path) -> None:
    legacy = source_root / "data"
    if not (legacy / "kroika.db").is_file() or legacy.resolve() == data_dir.resolve():
        return
    repository = SQLiteRepository(data_dir / "kroika.db")
    repository.initialize()
    with repository._connect() as connection:
        populated = any(connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()  # nosec B608 # fixed TABLE_KEYS allowlist
                        for table in TABLE_KEYS)
    if not populated:
        import_data(legacy, repository, data_dir / "images", home / "backups")
    old_profile = source_root / ".local-state" / "desktop" / "webview"
    profile = home / "webview"
    if old_profile.is_dir() and not profile.exists():
        home.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".profile-", dir=home))
        try:
            shutil.copytree(old_profile, temporary / "webview",
                            ignore=shutil.ignore_patterns("Singleton*", "LOCK", "lockfile"))
            (temporary / "webview").replace(profile)
        except OSError as error:
            raise BackupError("Не удалось перенести профиль окна. Закройте прежний запуск Кройки.") from error
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
