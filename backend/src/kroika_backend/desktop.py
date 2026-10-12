"""Desktop window and a supervised, loopback-only production API/UI server."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import importlib
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import os
from pathlib import Path
import socket
import secrets
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from .app import create_app
from .config import Settings
from .desktop_preferences import Preferences, desktop_home
from .desktop_data import import_data, migrate_legacy
from .backup import BackupError
from .errors import AppError
from .vision_providers import build_provider_registry
from kroika_contracts.resources import resource_root


DEFAULT_PORT = 18765
INSTANCE_HEADER = "X-Kroika-Desktop-Instance"
SOURCE_ROOT = resource_root()


class DesktopError(RuntimeError):
    """A launch failure that can be shown without exposing provider credentials."""


def bind_listener(port: int):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        return listener
    except OSError as error:
        listener.close()
        raise DesktopError(
            f"Не удалось занять локальный порт {port}. "
            "Закройте уже запущенную Кройку или укажите другой --port."
        ) from error


class DesktopFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Unknown API endpoints must not fall through to frontend files.
        if path.split("/", 1)[0] in {"api", "health", "_desktop"}:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        response = await super().get_response(path, scope)
        if path in {".", "", "index.html"}:
            response.headers["Cache-Control"] = "no-store"
        return response


def create_desktop_app(settings: Settings, frontend_dir: Path, port: int, instance_id: str,
                       control_token: str | None = None, backups: Path | None = None):
    frontend_dir = frontend_dir.resolve()
    if not (frontend_dir / "index.html").is_file():
        raise DesktopError(
            "Не найдена сборка интерфейса. Запустите scripts/start_desktop.py для её создания."
        )
    app = create_app(replace(settings, cors_origins=()))
    authority = f"127.0.0.1:{port}"
    origin = f"http://{authority}"

    @app.middleware("http")
    async def desktop_origin(request, call_next):
        if (request.headers.get("host") != authority
                or request.headers.get("origin") not in {None, origin}):
            return JSONResponse(
                {"code": "DESKTOP_ORIGIN_REJECTED", "message_ru": "Запрос вне окна приложения."},
                status_code=403,
            )
        if request.url.path.startswith("/_desktop/") and (
            not control_token or not secrets.compare_digest(
                request.headers.get("X-Kroika-Desktop-Token", ""), control_token,
            )
        ):
            return JSONResponse({"message_ru": "Действие недоступно вне приложения."}, status_code=403)
        response = await call_next(request)
        response.headers[INSTANCE_HEADER] = instance_id
        return response

    if control_token:
        @app.post("/_desktop/ai-settings", include_in_schema=False)
        def update_ai(payload: dict):
            if set(payload) != Preferences.FIELDS | {"api_key"}:
                raise AppError(422, "DESKTOP_SETTINGS_INVALID", "Некорректные настройки сервиса.")
            key = payload["api_key"]
            if key is not None and (not isinstance(key, str) or len(key) > 2048):
                raise AppError(422, "DESKTOP_SETTINGS_INVALID", "Некорректный ключ.")
            try:
                candidate = Preferences._apply(app.state.settings, {
                    field: payload[field] for field in Preferences.FIELDS
                }, key)
            except (ValueError, TypeError) as error:
                raise AppError(422, "DESKTOP_SETTINGS_INVALID", "Проверьте модель и параметры сервиса.") from error
            registry = build_provider_registry(candidate, app.state.image_store)
            # In-flight requests retain their already-selected provider instance.
            app.state.provider_registry = registry
            app.state.ai_provider = registry.get()
            app.state.settings = candidate
            return {"ok": True}

        @app.post("/_desktop/import", include_in_schema=False)
        def import_projects(payload: dict):
            if set(payload) != {"source"} or not isinstance(payload["source"], str):
                raise AppError(422, "DESKTOP_IMPORT_INVALID", "Выберите папку с данными Кройки.")
            try:
                return import_data(Path(payload["source"]), app.state.repository,
                                   app.state.image_store.root, backups)
            except BackupError as error:
                raise AppError(409, "DESKTOP_IMPORT_BLOCKED", str(error)) from error

    # Mount last: every existing API, image, preview and export route wins over static files.
    app.mount("/", DesktopFiles(directory=frontend_dir, html=True), name="desktop-ui")
    return app


def desktop_settings(data_dir: Path) -> Settings:
    settings = Settings.from_env()
    return replace(
        settings,
        database_path=Path(os.environ.get("KROIKA_DATABASE_PATH")
                           or data_dir / "kroika.db").expanduser().resolve(),
        image_storage_path=Path(os.environ.get("KROIKA_IMAGE_STORAGE_PATH")
                                or data_dir / "images").expanduser().resolve(),
    )


def _serve(settings, frontend_dir, listener, instance_id, stop_event, errors, control_token,
           home):
    """Spawn target uses no GUI imports and is compatible with Windows process startup."""
    try:
        import uvicorn

        port = listener.getsockname()[1]
        app = create_desktop_app(settings, frontend_dir, port, instance_id, control_token,
                                 home / "backups" if home else settings.database_path.parent / "backups")
        if home:
            from .logging_config import JsonFormatter

            logs = home / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(logs / "backend.log", maxBytes=2_000_000,
                                          backupCount=3, encoding="utf-8")
            handler.setFormatter(JsonFormatter())
            logging.getLogger("kroika.backend").addHandler(handler)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, access_log=False,
            log_level="warning", proxy_headers=False, timeout_graceful_shutdown=3,
            use_colors=False,
        )
        server = uvicorn.Server(config)

        async def serve():
            async def watch_stop():
                while not stop_event.is_set():
                    await asyncio.sleep(0.1)
                server.should_exit = True

            watcher = asyncio.create_task(watch_stop())
            try:
                await server.serve(sockets=[listener])
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

        asyncio.run(serve())
    except BaseException as error:
        # Do not send exception messages from providers/configuration to native error dialogs.
        errors.send(type(error).__name__)
    finally:
        listener.close()
        errors.close()


class DesktopServer:
    def __init__(self, settings: Settings, frontend_dir: Path, port: int = DEFAULT_PORT,
                 home: Path | None = None, listener=None):
        self.settings = settings
        self.frontend_dir = frontend_dir
        self.port = port
        self.instance_id = str(uuid4())
        self.control_token = secrets.token_urlsafe(32)
        self.home = home
        context = multiprocessing.get_context("spawn")
        self.stop_event = context.Event()
        self.errors, self._child_errors = context.Pipe(duplex=False)
        self.process = None
        self._listener = listener

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout_seconds: float = 45) -> None:
        try:
            self.settings.validate()
            if not (self.frontend_dir / "index.html").is_file():
                raise DesktopError("Интерфейс не собран. Запустите scripts/start_desktop.py.")
            self._listener = self._listener or bind_listener(self.port)
            self.port = self._listener.getsockname()[1]
            self.process = multiprocessing.get_context("spawn").Process(
                target=_serve,
                args=(self.settings, self.frontend_dir, self._listener, self.instance_id,
                      self.stop_event, self._child_errors, self.control_token, self.home),
                name="Kroika desktop backend", daemon=True,
            )
            self.process.start()
            self._child_errors.close()
            self._listener.close()
            self._listener = None
            self._wait_until_ready(timeout_seconds)
        except BaseException:
            self.stop()
            raise

    def _wait_until_ready(self, timeout_seconds: float) -> None:
        # System HTTP proxies must never intercept the local application.
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.errors.poll():
                try:
                    error_type = self.errors.recv()
                except EOFError:
                    error_type = None
                if error_type:
                    raise DesktopError(
                        f"Не удалось запустить локальный сервер ({error_type}). "
                        "Проверьте настройки запуска и доступ к папке данных."
                    )
            if not self.process.is_alive():
                raise DesktopError("Локальный сервер завершился до открытия окна.")
            try:
                with opener.open(Request(f"{self.url}/health/ready"), timeout=0.5) as response:
                    if (response.status == 200
                            and response.headers.get(INSTANCE_HEADER) == self.instance_id):
                        return
            except (OSError, URLError):
                pass
            time.sleep(0.1)
        raise DesktopError("Локальный сервер не запустился за отведённое время.")

    def stop(self) -> None:
        self.stop_event.set()
        if self.process is not None and self.process.pid is not None:
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        self._child_errors.close()
        self.errors.close()


def show_error(message: str) -> None:
    if sys.stderr is not None:
        print(f"Кройка: {message}", file=sys.stderr)
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Кройка — ошибка запуска", 0x10)


def run_desktop(settings: Settings, frontend_dir: Path, profile_dir: Path,
                port: int = DEFAULT_PORT, debug: bool = False, home: Path | None = None,
                listener=None, smoke_result: Path | None = None) -> None:
    try:
        webview = importlib.import_module("webview")
    except ImportError as error:
        raise DesktopError(
            "Не установлен компонент окна. Запустите scripts/start_desktop.py."
        ) from error
    profile_dir.mkdir(parents=True, exist_ok=True)
    home = home or profile_dir.parent
    preferences = Preferences(home)
    server = DesktopServer(settings, frontend_dir, port, home, listener)
    try:
        server.start()
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        from .desktop_bridge import DesktopBridge

        bridge = DesktopBridge(server, preferences, webview)
        window = webview.create_window(
            "Кройка", server.url, width=1440, height=960, min_size=(900, 640),
            text_select=True, zoomable=True, confirm_close=smoke_result is None, js_api=bridge,
        )
        bridge._window = window

        def monitor_backend():
            if smoke_result is not None:
                from .desktop_smoke import check_window
                check_window(window, smoke_result)
                return
            while server.process.is_alive() and not server.stop_event.wait(0.5):
                pass
            if not server.stop_event.is_set():
                show_error("Локальный сервер остановился. Откройте Кройку заново.")
                window.destroy()

        window.events.closed += server.stop_event.set
        webview.start(
            monitor_backend, gui="edgechromium" if os.name == "nt" else None,
            debug=debug, private_mode=False, storage_path=str(profile_dir.resolve()),
            icon=str(SOURCE_ROOT / "kroika.ico") if (SOURCE_ROOT / "kroika.ico").is_file() else None,
            localization={
                "global.quitConfirmation": "Закрыть Кройку? Завершите сохранение текущих изменений.",
                "global.ok": "ОК", "global.cancel": "Отмена",
                "global.saveFile": "Сохранить файл", "windows.fileFilter.allFiles": "Все файлы",
            },
        )
    except (DesktopError, ValueError):
        raise
    except Exception as error:
        raise DesktopError(
            "Не удалось открыть окно приложения. На Windows проверьте установку Microsoft "
            f"Edge WebView2 Runtime. Тип ошибки: {type(error).__name__}."
        ) from error
    finally:
        server.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Окно приложения Кройка")
    parser.add_argument("--frontend-dir", type=Path, default=SOURCE_ROOT / "frontend" / "dist")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--profile-dir", type=Path)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--self-test", type=Path, metavar="RESULT_JSON")
    parser.add_argument("--smoke-test", type=Path, metavar="RESULT_JSON")
    args = parser.parse_args(argv)
    if args.self_test:
        from .desktop_smoke import check_bundle
        return check_bundle(args.frontend_dir, args.self_test)
    if not 1 <= args.port <= 65535:
        parser.error("--port должен быть от 1 до 65535")
    try:
        home = desktop_home()
        with InstallerMutex(), DesktopLock(home / "desktop.lock"), bind_listener(args.port) as listener:
            data_dir = (args.data_dir or home / "data").expanduser().resolve()
            if (not getattr(sys, "frozen", False) and args.data_dir is None and not os.getenv("KROIKA_DATABASE_PATH")
                    and not os.getenv("KROIKA_IMAGE_STORAGE_PATH")):
                migrate_legacy(SOURCE_ROOT, data_dir, home)
            settings = Preferences(home).load(desktop_settings(data_dir))
            if getattr(sys, "frozen", False):
                from .desktop_upgrade import prepare_upgrade
                prepare_upgrade(settings, home)
            run_desktop(settings, args.frontend_dir, args.profile_dir or home / "webview",
                        args.port, args.debug, home, listener, args.smoke_test)
    except KeyboardInterrupt:
        return 0
    except (DesktopError, BackupError, ValueError, OSError) as error:
        # Settings validation messages contain variable names, never values/API keys.
        show_error(str(error) if isinstance(error, (DesktopError, BackupError, ValueError))
                   else "Не удалось прочитать или создать файлы приложения.")
        return 1
    return 0


class DesktopLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            raise DesktopError("Кройка уже открыта с этой папкой данных. Закройте прежнее окно.") from error
        return self

    def __exit__(self, *_):
        self.stream.close()


class InstallerMutex:
    """Tell Windows setup/uninstall to wait for every native window to close."""

    def __enter__(self):
        self.handle = None
        if os.name == "nt":
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            self.handle = kernel.CreateMutexW(None, False, "Kroika.Desktop.Window")
            if not self.handle:
                raise DesktopError("Не удалось зарегистрировать окно приложения.")
        return self

    def __exit__(self, *_):
        if self.handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            ctypes.windll.kernel32.CloseHandle(self.handle)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
