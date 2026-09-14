#!/usr/bin/env python3
"""End-to-end HTTP smoke test for measurement catalogue and profile storage."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "pattern-engine" / "src"),
                str(ROOT / "backend" / "src")]

from kroika_backend.app import create_app  # noqa: E402
from kroika_backend.config import Settings  # noqa: E402


def main() -> int:
    project = json.loads(
        (ROOT / "examples" / "v1" / "example-dress-project.json").read_text(encoding="utf-8")
    )
    profile = project["body_measurements"]
    with TemporaryDirectory(prefix="kroika-stage5-") as directory:
        app = create_app(Settings(database_path=Path(directory) / "smoke.db", log_level="CRITICAL"))
        with TestClient(app, raise_server_exceptions=False) as client:
            catalog = client.get("/api/v1/measurements/catalog?garment_type=dress")
            assert catalog.status_code == 200
            assert len(catalog.json()["measurements"]) >= 16
            validation = client.post(
                "/api/v1/measurements/validate?garment_type=dress", json=profile
            )
            assert validation.status_code == 200
            assert validation.json()["status"] == "ready"
            created = client.post("/api/v1/measurement-profiles", json=profile)
            assert created.status_code == 201
            assert client.get("/api/v1/measurement-profiles").json()["items"][0]["name"] == profile["name"]
            changed = dict(profile)
            changed["name"] = "Профиль после smoke-test"
            updated = client.put(
                f"/api/v1/measurement-profiles/{profile['profile_id']}",
                headers={"If-Match": "1"}, json=changed,
            )
            assert updated.status_code == 200
            assert updated.json()["revision"] == 2
    print("Smoke-test этапа 5 пройден: каталог, проверка и ревизии профиля работают.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
