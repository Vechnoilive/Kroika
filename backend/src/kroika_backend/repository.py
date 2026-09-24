"""SQLite adapters with explicit optimistic concurrency and JSON copies."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from kroika_contracts.semantic import validate_project
from kroika_contracts.measurements import validate_measurement_profile

from .errors import AppError


def _dump(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _load(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


GENERATION_INPUT_FIELDS = (
    "pattern_method",
    "body_measurements",
    "garment_spec",
    "fit_settings",
    "fabric_properties",
)


def _generation_input_snapshot(source: dict[str, Any]) -> dict[str, Any] | None:
    if not all(field in source for field in GENERATION_INPUT_FIELDS):
        return None
    return {field: deepcopy(source[field]) for field in GENERATION_INPUT_FIELDS}


def _change_summary(before: dict[str, Any] | None, after: dict[str, Any]) -> str:
    if before is None:
        return "Проект создан"
    if (before.get("latest_generation") != after.get("latest_generation")
            and after.get("latest_generation") is not None):
        return "Выкройка построена и проверена"
    changed: list[str] = []
    if (before.get("image_refs") != after.get("image_refs")
            or before.get("style_analysis_id") != after.get("style_analysis_id")):
        changed.append("изображения и анализ")
    if before.get("garment_spec") != after.get("garment_spec"):
        changed.append("фасон")
    if before.get("body_measurements") != after.get("body_measurements"):
        changed.append("мерки")
    if (before.get("fit_settings") != after.get("fit_settings")
            or before.get("fabric_properties") != after.get("fabric_properties")):
        changed.append("ткань и прибавки")
    if before.get("name") != after.get("name"):
        changed.append("название")
    return "Обновлены " + ", ".join(changed) if changed else "Черновик сохранён"


class SQLiteRepository:
    SCHEMA_VERSION = 2

    def __init__(self, database_path: Path):
        self.database_path = database_path

    @staticmethod
    def _make_private(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except OSError:
            # Windows uses ACLs rather than POSIX mode bits.
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._make_private(self.database_path.parent, 0o700)
        with self._connect() as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    "База данных создана более новой версией Kroika. "
                    "Откройте её совместимой версией приложения."
                )
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
                    engine_version TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (project_id, input_hash, engine_version),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS generations_project_idx
                    ON generations(project_id, created_at);
                CREATE TABLE IF NOT EXISTS measurement_profiles (
                    profile_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_revisions (
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    change_summary TEXT NOT NULL,
                    PRIMARY KEY (project_id, revision),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS project_revisions_project_idx
                    ON project_revisions(project_id, revision DESC);
            """)
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(generations)")
            }
            if "engine_version" not in columns:
                rows = connection.execute(
                    "SELECT generation_id, project_id, input_hash, payload, created_at FROM generations"
                ).fetchall()
                connection.executescript("""
                    CREATE TABLE generations_stage9 (
                        generation_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        input_hash TEXT NOT NULL,
                        engine_version TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE (project_id, input_hash, engine_version),
                        FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                    );
                """)
                for row in rows:
                    payload = _load(row["payload"])
                    connection.execute(
                        "INSERT INTO generations_stage9 "
                        "(generation_id, project_id, input_hash, engine_version, payload, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            row["generation_id"],
                            row["project_id"],
                            row["input_hash"],
                            str(payload.get("engine_version", "0.0.0")),
                            row["payload"],
                            row["created_at"],
                        ),
                    )
                connection.executescript("""
                    DROP TABLE generations;
                    ALTER TABLE generations_stage9 RENAME TO generations;
                    CREATE INDEX generations_project_idx
                        ON generations(project_id, created_at);
                """)
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS physical_validation_records (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL UNIQUE,
                    generation_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    gate TEXT NOT NULL CHECK (gate IN ('paper', 'expert', 'toile')),
                    outcome TEXT NOT NULL CHECK (outcome IN ('passed', 'failed')),
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (generation_id) REFERENCES generations(generation_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS physical_validation_generation_idx
                    ON physical_validation_records(generation_id, sequence DESC);
                CREATE TABLE IF NOT EXISTS generation_input_snapshots (
                    generation_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (generation_id) REFERENCES generations(generation_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS generation_input_snapshots_project_idx
                    ON generation_input_snapshots(project_id, created_at);
            """)
            connection.execute(
                "INSERT OR IGNORE INTO project_revisions "
                "(project_id, revision, payload, updated_at, change_summary) "
                "SELECT project_id, revision, payload, updated_at, ? FROM projects",
                ("Сохранённая версия до включения истории",),
            )
            missing_snapshots = connection.execute(
                "SELECT generation_id, project_id, created_at FROM generations "
                "WHERE generation_id NOT IN "
                "(SELECT generation_id FROM generation_input_snapshots)"
            ).fetchall()
            for generation in missing_snapshots:
                revisions = connection.execute(
                    "SELECT payload FROM project_revisions WHERE project_id = ? "
                    "ORDER BY revision DESC",
                    (generation["project_id"],),
                ).fetchall()
                snapshot = None
                for revision in revisions:
                    project = _load(revision["payload"])
                    latest = project.get("latest_generation") or {}
                    if latest.get("generation_id") == generation["generation_id"]:
                        snapshot = _generation_input_snapshot(project)
                        break
                if snapshot is not None:
                    connection.execute(
                        "INSERT OR IGNORE INTO generation_input_snapshots "
                        "(generation_id, project_id, payload, created_at) VALUES (?, ?, ?, ?)",
                        (
                            generation["generation_id"],
                            generation["project_id"],
                            _dump(snapshot),
                            generation["created_at"],
                        ),
                    )
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
        self._make_private(self.database_path, 0o600)

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

    def project_image_refs(self, project_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM projects WHERE project_id = ? "
                "UNION ALL SELECT payload FROM project_revisions WHERE project_id = ?",
                (project_id, project_id),
            ).fetchall()
            validation_rows = connection.execute(
                "SELECT payload FROM physical_validation_records WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        project_refs = {
            str(image_ref)
            for row in rows
            for image_ref in _load(row["payload"]).get("image_refs", [])
        }
        evidence_refs = {
            str(image_ref)
            for row in validation_rows
            for image_ref in _load(row["payload"]).get("evidence_image_refs", [])
        }
        return project_refs | evidence_refs

    def image_ref_in_use(self, image_ref: str) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM projects UNION ALL SELECT payload FROM project_revisions"
            ).fetchall()
            validation_rows = connection.execute(
                "SELECT payload FROM physical_validation_records"
            ).fetchall()
        return (
            any(image_ref in _load(row["payload"]).get("image_refs", []) for row in rows)
            or any(
                image_ref in _load(row["payload"]).get("evidence_image_refs", [])
                for row in validation_rows
            )
        )

    def delete_project(self, project_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE project_id = ?", (project_id,)
            )
        return cursor.rowcount == 1

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
                connection.execute(
                    "INSERT INTO project_revisions "
                    "(project_id, revision, payload, updated_at, change_summary) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        document["project_id"], document["revision"], _dump(document),
                        document["updated_at"], _change_summary(None, document),
                    ),
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
            if (document["body_measurements"] != stored["body_measurements"]
                    and document["status"] != "draft"):
                raise AppError(
                    422, "PROJECT_MEASUREMENTS_CHANGED_WITH_ACTIVE_STATUS",
                    "После изменения мерок переведите проект в черновик и повторите проверку входов.",
                )
            document["created_at"] = stored["created_at"]
            document["revision"] = expected_revision + 1
            document["updated_at"] = _now()
            if any(document[field] != stored[field] for field in GENERATION_INPUT_FIELDS):
                document["latest_generation"] = None
                document["status"] = "draft"
            validate_project(document)
            cursor = connection.execute(
                "UPDATE projects SET revision = ?, payload = ?, updated_at = ? "
                "WHERE project_id = ? AND revision = ?",
                (document["revision"], _dump(document), document["updated_at"],
                 project_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise AppError(409, "PROJECT_REVISION_CONFLICT", "Проект был изменён. Обновите страницу.")
            connection.execute(
                "INSERT INTO project_revisions "
                "(project_id, revision, payload, updated_at, change_summary) VALUES (?, ?, ?, ?, ?)",
                (
                    project_id, document["revision"], _dump(document), document["updated_at"],
                    _change_summary(stored, document),
                ),
            )
        return deepcopy(document)

    def list_project_history(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            current = connection.execute(
                "SELECT revision FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if current is None:
                return []
            rows = connection.execute(
                "SELECT revision, payload, updated_at, change_summary "
                "FROM project_revisions WHERE project_id = ? ORDER BY revision DESC",
                (project_id,),
            ).fetchall()
        return [{
            "revision": row["revision"],
            "status": _load(row["payload"])["status"],
            "updated_at": row["updated_at"],
            "change_summary": row["change_summary"],
            "is_current": row["revision"] == current["revision"],
        } for row in rows]

    def restore_project_revision(
        self, project_id: str, revision: int, expected_revision: int,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_row = connection.execute(
                "SELECT revision, payload FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if current_row is None:
                raise AppError(404, "PROJECT_NOT_FOUND", "Проект не найден.")
            if current_row["revision"] != expected_revision:
                raise AppError(
                    409, "PROJECT_REVISION_CONFLICT",
                    "Проект уже изменён в другой вкладке. Обновите страницу.",
                )
            target_row = connection.execute(
                "SELECT payload FROM project_revisions WHERE project_id = ? AND revision = ?",
                (project_id, revision),
            ).fetchone()
            if target_row is None:
                raise AppError(404, "PROJECT_REVISION_NOT_FOUND", "Выбранная версия не найдена.")
            current = _load(current_row["payload"])
            target = _load(target_row["payload"])
            document = deepcopy(target)
            document["revision"] = expected_revision + 1
            document["created_at"] = current["created_at"]
            document["updated_at"] = _now()
            document["status"] = "draft"
            document["latest_generation"] = None
            document["generation_history"] = deepcopy(current["generation_history"])
            validate_project(document)
            connection.execute(
                "UPDATE projects SET revision = ?, payload = ?, updated_at = ? WHERE project_id = ?",
                (document["revision"], _dump(document), document["updated_at"], project_id),
            )
            connection.execute(
                "INSERT INTO project_revisions "
                "(project_id, revision, payload, updated_at, change_summary) VALUES (?, ?, ?, ?, ?)",
                (
                    project_id, document["revision"], _dump(document), document["updated_at"],
                    f"Восстановлена версия {revision} как новый черновик",
                ),
            )
        return deepcopy(document)

    def list_measurement_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT revision, payload, updated_at FROM measurement_profiles "
                "ORDER BY updated_at DESC, profile_id ASC"
            ).fetchall()
        summaries = []
        for row in rows:
            profile = _load(row["payload"])
            summaries.append({
                "profile_id": profile["profile_id"],
                "name": profile["name"],
                "status": profile["status"],
                "revision": row["revision"],
                "updated_at": row["updated_at"],
            })
        return summaries

    def get_measurement_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision, payload, updated_at FROM measurement_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "revision": row["revision"],
            "updated_at": row["updated_at"],
            "profile": _load(row["payload"]),
        }

    def delete_measurement_profile(self, profile_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM measurement_profiles WHERE profile_id = ?", (profile_id,)
            )
        return cursor.rowcount == 1

    def create_measurement_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        validate_measurement_profile(profile)
        document = deepcopy(profile)
        updated_at = _now()
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO measurement_profiles(profile_id, revision, payload, updated_at) "
                    "VALUES (?, 1, ?, ?)",
                    (document["profile_id"], _dump(document), updated_at),
                )
        except sqlite3.IntegrityError as exc:
            raise AppError(
                409, "MEASUREMENT_PROFILE_ALREADY_EXISTS",
                "Профиль мерок с таким номером уже существует.",
            ) from exc
        return {"revision": 1, "updated_at": updated_at, "profile": deepcopy(document)}

    def replace_measurement_profile(
        self, profile_id: str, expected_revision: int, profile: dict[str, Any],
    ) -> dict[str, Any]:
        validate_measurement_profile(profile)
        if profile["profile_id"] != profile_id:
            raise AppError(
                422, "MEASUREMENT_PROFILE_ID_MISMATCH",
                "Номер профиля в адресе и документе не совпадает.",
            )
        document = deepcopy(profile)
        updated_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM measurement_profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
            if row is None:
                raise AppError(404, "MEASUREMENT_PROFILE_NOT_FOUND", "Профиль мерок не найден.")
            if row["revision"] != expected_revision:
                raise AppError(
                    409, "MEASUREMENT_PROFILE_REVISION_CONFLICT",
                    "Профиль уже изменён. Обновите список и повторите действие.",
                )
            cursor = connection.execute(
                "UPDATE measurement_profiles SET revision = ?, payload = ?, updated_at = ? "
                "WHERE profile_id = ? AND revision = ?",
                (expected_revision + 1, _dump(document), updated_at, profile_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise AppError(
                    409, "MEASUREMENT_PROFILE_REVISION_CONFLICT",
                    "Профиль уже изменён. Обновите список и повторите действие.",
                )
        return {
            "revision": expected_revision + 1,
            "updated_at": updated_at,
            "profile": deepcopy(document),
        }

    def get_generation(self, generation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM generations WHERE generation_id = ?", (generation_id,)
            ).fetchone()
        return _load(row["payload"]) if row else None

    def list_generations(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT g.payload, s.generation_id AS snapshot_generation_id "
                "FROM generations AS g LEFT JOIN generation_input_snapshots AS s "
                "ON s.generation_id = g.generation_id "
                "WHERE g.project_id = ? ORDER BY g.created_at DESC, g.generation_id DESC",
                (project_id,),
            ).fetchall()
        return [{
            "result": _load(row["payload"]),
            "comparable": row["snapshot_generation_id"] is not None,
        } for row in rows]

    def get_generation_input_snapshot(self, generation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM generation_input_snapshots WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
        return _load(row["payload"]) if row else None

    @staticmethod
    def _store_generation_input_snapshot(
        connection: sqlite3.Connection,
        result: dict[str, Any],
        source: dict[str, Any] | None,
    ) -> None:
        if source is None:
            return
        snapshot = _generation_input_snapshot(source)
        if snapshot is None:
            return
        connection.execute(
            "INSERT OR IGNORE INTO generation_input_snapshots "
            "(generation_id, project_id, payload, created_at) VALUES (?, ?, ?, ?)",
            (
                result["generation_id"], result["project_id"], _dump(snapshot),
                result["created_at"],
            ),
        )

    def physical_validation_summary(self, generation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            generation = connection.execute(
                "SELECT project_id FROM generations WHERE generation_id = ?", (generation_id,)
            ).fetchone()
            if generation is None:
                return None
            rows = connection.execute(
                "SELECT payload FROM physical_validation_records "
                "WHERE generation_id = ? ORDER BY sequence DESC",
                (generation_id,),
            ).fetchall()
        records = [_load(row["payload"]) for row in rows]
        for record in records:
            record.setdefault("evidence_image_refs", [])
        required = {"paper": 2, "expert": 1, "toile": 3}
        gates: list[dict[str, Any]] = []
        for gate in ("paper", "expert", "toile"):
            gate_records = [record for record in records if record["gate"] == gate]
            latest = gate_records[0] if gate_records else None
            if gate == "expert":
                current = [latest] if latest else []
            else:
                scope_field = "printer_name" if gate == "paper" else "figure_label"
                current_by_scope: dict[str, dict[str, Any]] = {}
                for record in gate_records:
                    scope = str(record.get(scope_field) or "").strip().casefold()
                    current_by_scope.setdefault(scope, record)
                current = list(current_by_scope.values())
            passed = sum(record["outcome"] == "passed" for record in current)
            if any(record["outcome"] == "failed" for record in current):
                status = "failed"
            elif passed >= required[gate]:
                status = "passed"
            else:
                status = "pending"
            gates.append({
                "gate": gate,
                "status": status,
                "latest_record_id": latest["record_id"] if latest else None,
                "checked_at": latest["created_at"] if latest else None,
                "passed_observations": passed,
                "required_observations": required[gate],
            })
        return {
            "project_id": generation["project_id"],
            "generation_id": generation_id,
            "gates": gates,
            "production_allowed": all(gate["status"] == "passed" for gate in gates),
            "policy": (
                "Допуск относится только к этой версии: нужны успешные проверки на двух "
                "разных принтерах, заключение конструктора и три макета на разных фигурах; "
                "последняя отрицательная запись соответствующей проверки снимает допуск."
            ),
            "records": records,
        }

    def add_physical_validation(
        self, generation_id: str, observation: dict[str, Any]
    ) -> dict[str, Any]:
        with self._connect() as connection:
            generation = connection.execute(
                "SELECT project_id FROM generations WHERE generation_id = ?", (generation_id,)
            ).fetchone()
            if generation is None:
                raise AppError(404, "GENERATION_NOT_FOUND", "Результат построения не найден.")
            document = deepcopy(observation)
            document.update({
                "record_id": str(uuid4()),
                "project_id": generation["project_id"],
                "generation_id": generation_id,
                "created_at": _now(),
            })
            connection.execute(
                "INSERT INTO physical_validation_records "
                "(record_id, generation_id, project_id, gate, outcome, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    document["record_id"], generation_id, generation["project_id"],
                    document["gate"], document["outcome"], _dump(document),
                    document["created_at"],
                ),
            )
        summary = self.physical_validation_summary(generation_id)
        if summary is None:  # pragma: no cover - protected by the transaction above.
            raise AppError(404, "GENERATION_NOT_FOUND", "Результат построения не найден.")
        return summary

    def get_generation_by_hash(
        self, project_id: str, input_hash: str, engine_version: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM generations "
                "WHERE project_id = ? AND input_hash = ? AND engine_version = ?",
                (project_id, input_hash, engine_version),
            ).fetchone()
        return _load(row["payload"]) if row else None

    def activate_generation(
        self,
        result: dict[str, Any],
        input_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach an existing immutable result to the current matching inputs."""

        project_id = result["project_id"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, payload FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise AppError(404, "PROJECT_NOT_FOUND", "Сначала сохраните проект.")
            self._store_generation_input_snapshot(connection, result, input_snapshot)
            project = _load(row["payload"])
            if (project.get("latest_generation") or {}).get("generation_id") == result["generation_id"]:
                return deepcopy(result)
            project["latest_generation"] = deepcopy(result)
            if not any(
                item["generation_id"] == result["generation_id"]
                for item in project["generation_history"]
            ):
                project["generation_history"].append({
                    "generation_id": result["generation_id"],
                    "input_hash": result["input_hash"],
                    "engine_version": result["engine_version"],
                    "method_version": result["pattern_method"]["version"],
                    "created_at": result["created_at"],
                    "status": result["status"],
                })
            project["status"] = (
                "validation_failed"
                if result["validation_report"]["status"] == "failed" else "generated"
            )
            project["revision"] = row["revision"] + 1
            project["updated_at"] = _now()
            validate_project(project)
            connection.execute(
                "UPDATE projects SET revision = ?, payload = ?, updated_at = ? WHERE project_id = ?",
                (project["revision"], _dump(project), project["updated_at"], project_id),
            )
            connection.execute(
                "INSERT INTO project_revisions "
                "(project_id, revision, payload, updated_at, change_summary) VALUES (?, ?, ?, ?, ?)",
                (
                    project_id, project["revision"], _dump(project), project["updated_at"],
                    "Повторно открыт сохранённый результат построения",
                ),
            )
        return deepcopy(result)

    def record_generation(
        self,
        result: dict[str, Any],
        input_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project_id = result["project_id"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload FROM generations "
                "WHERE project_id = ? AND input_hash = ? AND engine_version = ?",
                (project_id, result["input_hash"], result["engine_version"]),
            ).fetchone()
            if existing:
                stored = _load(existing["payload"])
                self._store_generation_input_snapshot(connection, stored, input_snapshot)
                return stored
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
                "INSERT INTO generations"
                "(generation_id, project_id, input_hash, engine_version, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    result["generation_id"],
                    project_id,
                    result["input_hash"],
                    result["engine_version"],
                    _dump(result),
                    result["created_at"],
                ),
            )
            self._store_generation_input_snapshot(connection, result, input_snapshot)
            connection.execute(
                "UPDATE projects SET revision = ?, payload = ?, updated_at = ? WHERE project_id = ?",
                (project["revision"], _dump(project), project["updated_at"], project_id),
            )
            connection.execute(
                "INSERT INTO project_revisions "
                "(project_id, revision, payload, updated_at, change_summary) VALUES (?, ?, ?, ?, ?)",
                (
                    project_id, project["revision"], _dump(project), project["updated_at"],
                    "Выкройка построена и проверена",
                ),
            )
        return deepcopy(result)

    def record_manual_generation(
        self,
        result: dict[str, Any],
        input_snapshot: dict[str, Any],
        *,
        base_generation_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Atomically append an edited generation without overwriting its parent."""

        project_id = result["project_id"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, payload FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise AppError(404, "PROJECT_NOT_FOUND", "Сначала сохраните проект.")
            project = _load(row["payload"])
            current_generation_id = (project.get("latest_generation") or {}).get(
                "generation_id"
            )
            if current_generation_id == result["generation_id"]:
                stored = connection.execute(
                    "SELECT payload FROM generations WHERE generation_id = ?",
                    (result["generation_id"],),
                ).fetchone()
                return _load(stored["payload"]) if stored else deepcopy(result)
            if row["revision"] != expected_revision:
                raise AppError(
                    409,
                    "PROJECT_REVISION_CONFLICT",
                    "Проект уже изменён. Обновите страницу перед сохранением ручной правки.",
                )
            if current_generation_id != base_generation_id:
                raise AppError(
                    409,
                    "MANUAL_BASE_NOT_CURRENT",
                    "Редактируемая версия уже не является текущей. Откройте последнюю выкройку.",
                )
            connection.execute(
                "INSERT INTO generations"
                "(generation_id, project_id, input_hash, engine_version, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    result["generation_id"], project_id, result["input_hash"],
                    result["engine_version"], _dump(result), result["created_at"],
                ),
            )
            self._store_generation_input_snapshot(connection, result, input_snapshot)
            project["latest_generation"] = deepcopy(result)
            project["generation_history"].append({
                "generation_id": result["generation_id"],
                "input_hash": result["input_hash"],
                "engine_version": result["engine_version"],
                "method_version": result["pattern_method"]["version"],
                "created_at": result["created_at"],
                "status": result["status"],
            })
            project["status"] = "generated"
            project["revision"] = row["revision"] + 1
            project["updated_at"] = _now()
            validate_project(project)
            connection.execute(
                "UPDATE projects SET revision = ?, payload = ?, updated_at = ? WHERE project_id = ?",
                (project["revision"], _dump(project), project["updated_at"], project_id),
            )
            connection.execute(
                "INSERT INTO project_revisions "
                "(project_id, revision, payload, updated_at, change_summary) VALUES (?, ?, ?, ?, ?)",
                (
                    project_id, project["revision"], _dump(project), project["updated_at"],
                    "Сохранена проверенная ручная правка геометрии",
                ),
            )
        return deepcopy(result)
