"""Limited native actions; untrusted pages never gain filesystem/credential access."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import RLock
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID

from .desktop_preferences import Preferences, PreferenceError


EXPORTS = {
    "a4-pdf": ("a4-pdf", "POST", "pdf"),
    "scale-check-pdf": ("scale-check-pdf", "POST", "pdf"),
    "print-svg": ("print.svg", "GET", "svg"),
    "project-json": ("project-json", "GET", "json"),
    "acceptance-report": (None, "GET", "pdf"),
}


class DesktopBridge:
    def __init__(self, server, preferences: Preferences, webview):
        self._server = server
        self._preferences = preferences
        self._webview = webview
        self._window = None
        self._lock = RLock()

    def _guard(self):
        url = self._window.get_current_url() if self._window is not None else None
        parsed = urlparse(url or "")
        if (f"{parsed.scheme}://{parsed.netloc}" != self._server.url
                or parsed.path not in {"", "/", "/index.html"}):
            raise PreferenceError("Это действие доступно только в окне Кройки.")

    def _result(self, action):
        with self._lock:
            try:
                self._guard()
                return {"ok": True, "value": action()}
            except PreferenceError as error:
                return {"ok": False, "message": str(error)}
            except Exception:
                return {"ok": False, "message": "Не удалось выполнить действие. Проверьте доступ к файлам и настройки."}

    def _request(self, path, method="GET", body=None, timeout=180):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self._server.url + path, data=data, method=method, headers={
            "Content-Type": "application/json", "X-Kroika-Desktop-Token": self._server.control_token,
        })
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as error:
            try:
                message = json.loads(error.read()).get("message_ru")
            except (ValueError, OSError):
                message = None
            raise PreferenceError(message or "Локальный сервер не выполнил действие.") from error

    def get_settings(self):
        return self._result(lambda: self._preferences.describe(self._server.settings))

    def save_settings(self, payload):
        def save():
            previous = self._server.settings
            candidate, document = self._preferences.prepare(payload, previous)
            self._apply(candidate)
            try:
                self._preferences.commit(candidate, document)
            except Exception:
                self._apply(previous)
                raise
            self._server.settings = candidate
            return self._preferences.describe(candidate)
        return self._result(save)

    def _apply(self, settings):
        self._request("/_desktop/ai-settings", "POST", {
            **Preferences._values(settings), "api_key": settings.gemini_api_key,
        })

    def choose_images(self):
        def choose():
            selected = self._window.create_file_dialog(
                self._webview.FileDialog.OPEN, allow_multiple=True,
                file_types=("Фотографии (*.jpg;*.jpeg;*.png;*.webp)",),
            )
            if not selected:
                return []
            if len(selected) > 4:
                raise PreferenceError("Выберите не больше четырёх фотографий за раз.")
            result = []
            for value in selected:
                path = Path(value)
                media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                              ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower())
                if media_type is None:
                    raise PreferenceError("Выберите изображения JPEG, PNG или WebP.")
                with path.open("rb") as stream:
                    content = stream.read(self._server.settings.max_image_bytes + 1)
                if not content or len(content) > self._server.settings.max_image_bytes:
                    raise PreferenceError("Фотография слишком большая или пустая.")
                result.append({"name": path.name, "type": media_type,
                               "last_modified": int(path.stat().st_mtime * 1000),
                               "data_base64": base64.b64encode(content).decode("ascii")})
            return result
        return self._result(choose)

    def save_export(self, generation_id, kind):
        def save():
            try:
                generation = str(UUID(generation_id))
                route, method, extension = EXPORTS[kind]
            except (ValueError, TypeError, KeyError) as error:
                raise PreferenceError("Неизвестный файл выкройки.") from error
            endpoint = (f"/api/v1/patterns/{generation}/export/{route}" if route else
                        f"/api/v1/patterns/{generation}/physical-validation/report.pdf")
            content = self._request(endpoint, method)
            selected = self._window.create_file_dialog(
                self._webview.FileDialog.SAVE, save_filename=f"kroika-{generation}-{kind}.{extension}",
                file_types=(f"Файл выкройки (*.{extension})",),
            )
            if not selected:
                return {"cancelled": True}
            destination = Path(selected[0])
            resolved = destination.resolve()
            database = self._server.settings.database_path.resolve()
            managed = {self._preferences.path.resolve(), database,
                       Path(str(database) + "-wal"), Path(str(database) + "-shm")}
            protected_folders = [self._server.settings.image_storage_path.resolve(),
                                 (self._preferences.home / "webview").resolve()]
            if resolved in managed or any(resolved.is_relative_to(path) for path in protected_folders):
                raise PreferenceError("Выберите другую папку: этот файл используется приложением.")
            descriptor, temporary = tempfile.mkstemp(prefix=".kroika-export-", dir=destination.parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return {"cancelled": False, "path": str(destination)}
        return self._result(save)

    def import_data(self):
        def import_folder():
            selected = self._window.create_file_dialog(self._webview.FileDialog.FOLDER)
            if not selected:
                return {"cancelled": True}
            content = self._request("/_desktop/import", "POST", {"source": selected[0]}, timeout=600)
            return {"cancelled": False, **json.loads(content)}
        return self._result(import_folder)

    def open_folder(self, kind):
        def open_known():
            folders = {"data": self._server.settings.database_path.parent,
                       "logs": self._preferences.home / "logs",
                       "backups": self._preferences.home / "backups"}
            if kind not in folders:
                raise PreferenceError("Неизвестная папка приложения.")
            path = folders[kind]
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
            return None
        return self._result(open_known)
