"""Desktop window and a supervised, loopback-only production API/UI server."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import importlib
import multiprocessing
import os
from pathlib import Path
import socket
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from .app import create_app
from .config import Settings


DEFAULT_PORT = 18765
INSTANCE_HEADER = "X-Kroika-Desktop-Instance"
SOURCE_ROOT = Path(__file__).resolve().parents[3]


class DesktopError(RuntimeError):
    """A launch failure that can be shown without exposing provider credentials."""


class DesktopFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Unknown API endpoints must not fall through to frontend files.
        if path.split("/", 1)[0] in {"api", "health"}:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        response = await super().get_response(path, scope)
        if path in {".", "", "index.html"}:
            response.headers["Cache-Control"] = "no-store"
        return response


def create_desktop_app(settings: Settings, frontend_dir: Path, port: int, instance_id: str):
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
        response = await call_next(request)
        response.headers[INSTANCE_HEADER] = instance_id
        return response

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


def _serve(settings, frontend_dir, listener, instance_id, stop_event, errors):
    """Spawn target uses no GUI imports and is compatible with Windows process startup."""
    try:
        import uvicorn

        port = listener.getsockname()[1]
        app = create_desktop_app(settings, frontend_dir, port, instance_id)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, access_log=False,
            log_level="warning", proxy_headers=False, timeout_graceful_shutdown=3,
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
    def __init__(self, settings: Settings, frontend_dir: Path, port: int = DEFAULT_PORT):
        self.settings = settings
        self.frontend_dir = frontend_dir
        self.port = port
        self.instance_id = str(uuid4())
        context = multiprocessing.get_context("spawn")
        self.stop_event = context.Event()
        self.errors, self._child_errors = context.Pipe(duplex=False)
        self.process = None
        self._listener = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout_seconds: float = 45) -> None:
        try:
            self.settings.validate()
            if not (self.frontend_dir / "index.html").is_file():
                raise DesktopError("Интерфейс не собран. Запустите scripts/start_desktop.py.")
            self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name == "nt":
                self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                # Rebind after graceful close/TIME_WAIT, without sharing an active listener.
                self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._listener.bind(("127.0.0.1", self.port))
                self._listener.listen(128)
            except OSError as error:
                raise DesktopError(
                    f"Не удалось занять локальный порт {self.port}. "
                    "Закройте уже запущенную Кройку или укажите другой --port."
                ) from error
            self.port = self._listener.getsockname()[1]
            self.process = multiprocessing.get_context("spawn").Process(
                target=_serve,
                args=(self.settings, self.frontend_dir, self._listener, self.instance_id,
                      self.stop_event, self._child_errors),
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
                port: int = DEFAULT_PORT, debug: bool = False) -> None:
    try:
        webview = importlib.import_module("webview")
    except ImportError as error:
        raise DesktopError(
            "Не установлен компонент окна. Запустите scripts/start_desktop.py."
        ) from error
    profile_dir.mkdir(parents=True, exist_ok=True)
    server = DesktopServer(settings, frontend_dir, port)
    try:
        server.start()
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["ALLOW_FILE_URLS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        window = webview.create_window(
            "Кройка", server.url, width=1440, height=960, min_size=(900, 640),
            text_select=True, zoomable=True, confirm_close=True,
        )

        def monitor_backend():
            while server.process.is_alive() and not server.stop_event.wait(0.5):
                pass
            if not server.stop_event.is_set():
                show_error("Локальный сервер остановился. Откройте Кройку заново.")
                window.destroy()

        window.events.closed += server.stop_event.set
        webview.start(
            monitor_backend, gui="edgechromium" if os.name == "nt" else None,
            debug=debug, private_mode=False, storage_path=str(profile_dir.resolve()),
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
    parser.add_argument("--data-dir", type=Path, default=SOURCE_ROOT / "data")
    parser.add_argument("--profile-dir", type=Path,
                        default=SOURCE_ROOT / ".local-state" / "desktop" / "webview")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port должен быть от 1 до 65535")
    try:
        run_desktop(desktop_settings(args.data_dir), args.frontend_dir,
                    args.profile_dir, args.port, args.debug)
    except KeyboardInterrupt:
        return 0
    except (DesktopError, ValueError, OSError) as error:
        # Settings validation messages contain variable names, never values/API keys.
        show_error(str(error) if isinstance(error, (DesktopError, ValueError))
                   else "Не удалось прочитать или создать файлы приложения.")
        return 1
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
