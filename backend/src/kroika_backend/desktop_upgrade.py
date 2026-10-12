"""Keep a checked pre-upgrade snapshot outside the replaceable application folder."""

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from .backup import create_backup, verify_backup
from .desktop_preferences import atomic_json, PreferenceError
from .desktop_version import VERSION


def prepare_upgrade(settings, home: Path) -> None:
    marker = home / "installed-version.json"
    previous = None
    if marker.exists():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))["version"]
        except (ValueError, KeyError, TypeError) as error:
            raise PreferenceError("Повреждена запись версии приложения: installed-version.json.") from error
    if previous == VERSION:
        return
    if settings.database_path.is_file():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = home / "backups" / f"before-desktop-{VERSION}-{timestamp}-{uuid4().hex[:8]}"
        create_backup(settings.database_path, settings.image_storage_path, target)
        verify_backup(target)
    atomic_json(marker, {"version": VERSION})
