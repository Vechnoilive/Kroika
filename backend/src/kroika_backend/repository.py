"""SQLite adapters with explicit optimistic concurrency and JSON copies."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from kroika_contracts.semantic import validate_project

from .errors import AppError


def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _load(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SQLiteRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generations (
                    generation_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (project_id, input_hash),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS generations_project_idx
                    ON generations(project_id, created_at);
            """)

    def health(self) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM projects ORDER BY updated_at DESC, project_id ASC"
            ).fetchall()
        return [_load(row["payload"]) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return _load(row["payload"]) if row else None

    def create_project(self, project: dict[str, Any]) -> dict[str, Any]:
        validate_project(project)
        if project["revision"] != 1:
            raise AppError(422, "PROJECT_REVISION_INVALID", "Новый проект должен иметь ревизию 1.")
        document = deepcopy(project)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO projects(project_id, revision, payload, updated_at) VALUES (?, ?, ?, ?)",
                    (document["project_id"], document["revision"], _dump(document), document["updated_at"]),
                )
        except sqlite3.IntegrityError as exc:
            raise AppError(409, "PROJECT_ALREADY_EXISTS", "Проект с таким номером уже существует.") from exc
        return deepcopy(document)

    def replace_project(self, project_id: str, expected_revision: int,
                        project: dict[str, Any]) -> dict[str, Any]:
        validate_project(project)
        if project["project_id"] != project_id:
            raise AppError(422, "PROJECT_ID_MISMATCH", "Номер проекта в адресе и документе не совпадает.")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, payload FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise AppError(404, "PROJECT_NOT_FOUND", "Проект не найден.")
            if row["revision"] != expected_revision or project["revision"] != expected_revision:
                raise AppError(
                    409, "PROJECT_REVISION_CONFLICT",
                    "Проект уже изменён в другой вкладке. Обновите страницу и повторите действие.",
                )
            stored = _load(row["payload"])
            document = deepcopy(project)
            document["created_at"] = stored["created_at"]
            document["revision"] = expected_revision + 1
            document["updated_at"] = _now()
            validate_project(document)
            cursor = connection.execute(
                "UPDATE projects SET revision = ?, payload = ?, updated_at = ? "
                "WHERE project_id = ? AND revision = ?",
                (document["revision"], _dump(document), document["updated_at"],
                 project_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise AppError(409, "PROJECT_REVISION_CONFLICT", "Проект был изменён. Обновите страницу.")
        return deepcopy(document)

    def get_generation(self, generation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM generations WHERE generation_id = ?", (generation_id,)
            ).fetchone()
        return _load(row["payload"]) if row else None

    def get_generation_by_hash(self, project_id: str, input_hash: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM generations WHERE project_id = ? AND input_hash = ?",
                (project_id, input_hash),
            ).fetchone()
        return _load(row["payload"]) if row else None

    def record_generation(self, result: dict[str, Any]) -> dict[str, Any]:
        project_id = result["project_id"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload FROM generations WHERE project_id = ? AND input_hash = ?",
                (project_id, result["input_hash"]),
            ).fetchone()
            if existing:
                return _load(existing["payload"])
            row = connection.execute(
                "SELECT revision, payload FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise AppError(404, "PROJECT_NOT_FOUND", "Сначала сохраните проект.")

            project = _load(row["payload"])
            project["latest_generation"] = deepcopy(result)
            project["generation_history"].append({
                "generation_id": result["generation_id"],
                "input_hash": result["input_hash"],
                "engine_version": result["engine_version"],
                "method_version": result["pattern_method"]["version"],
                "created_at": result["created_at"],
                "status": result["status"],
            })
            project["status"] = (
                "validation_failed" if result["validation_report"]["status"] == "failed" else "generated"
            )
            project["revision"] = row["revision"] + 1
            project["updated_at"] = _now()
            validate_project(project)

            connection.execute(
                "INSERT INTO generations(generation_id, project_id, input_hash, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (result["generation_id"], project_id, result["input_hash"],
                 _dump(result), result["created_at"]),
            )
            connection.execute(
                "UPDATE projects SET revision = ?, payload = ?, updated_at = ? WHERE project_id = ?",
                (project["revision"], _dump(project), project["updated_at"], project_id),
            )
        return deepcopy(result)
