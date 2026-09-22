#!/usr/bin/env python3
"""Cross-platform one-command bootstrap and local development launcher."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
STATE = ROOT / ".local-state"


def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _npm() -> str:
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not executable:
        raise SystemExit("Не найден Node.js/npm. Установите Node.js 24 LTS и повторите запуск.")
    return executable


def _node() -> str:
    executable = shutil.which("node.exe" if os.name == "nt" else "node")
    if not executable:
        raise SystemExit("Не найден Node.js. Установите Node.js 24 LTS и повторите запуск.")
    return executable


def _fingerprint() -> str:
    digest = hashlib.sha256()
    for path in (
        ROOT / "requirements-stage3.txt",
        ROOT / "requirements-stage4.txt",
        ROOT / "requirements-stage5.txt",
        ROOT / "requirements-stage6.txt",
        ROOT / "requirements-stage7.txt",
        ROOT / "requirements-stage8.txt",
        ROOT / "requirements-stage9.txt",
        ROOT / "requirements-stage10.txt",
        ROOT / "requirements-stage11.txt",
        ROOT / "requirements-stage12.txt",
        ROOT / "requirements-stage13.txt",
        ROOT / "requirements-stage14.txt",
        ROOT / "requirements-runtime.txt",
        ROOT / "requirements-stage15.txt",
        ROOT / "requirements-stage16.txt",
        ROOT / "pyproject.toml",
        ROOT / "pattern-engine" / "pyproject.toml",
        ROOT / "backend" / "pyproject.toml",
        ROOT / "frontend" / "package-lock.json",
    ):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def bootstrap() -> None:
    python = _venv_python()
    if not python.exists():
        print("Создаём локальное Python-окружение…")
        venv.EnvBuilder(with_pip=True).create(VENV)
    npm = _npm()
    fingerprint = _fingerprint()
    stamp = STATE / "bootstrap.sha256"
    if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == fingerprint:
        return

    print("Устанавливаем Python-зависимости…")
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-stage16.txt")],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", "-e", ".", "-e", "pattern-engine", "-e", "backend"],
        cwd=ROOT,
        check=True,
    )
    print("Устанавливаем frontend-зависимости…")
    subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
    STATE.mkdir(parents=True, exist_ok=True)
    stamp.write_text(fingerprint + "\n", encoding="utf-8")


def _wait_until_ready(process: subprocess.Popen, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit("Backend завершился раньше запуска. Посмотрите сообщение выше.")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise SystemExit("Backend не успел запуститься за 30 секунд.")


def run(open_browser: bool) -> None:
    python = _venv_python()
    node = _node()
    environment = os.environ.copy()
    environment.setdefault("KROIKA_DATABASE_PATH", str(ROOT / "data" / "kroika.db"))
    environment.setdefault("KROIKA_AI_PROVIDER", "mock")
    backend = subprocess.Popen(
        [str(python), "-m", "uvicorn", "kroika_backend.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
        cwd=ROOT,
        env=environment,
    )
    frontend: subprocess.Popen | None = None
    try:
        _wait_until_ready(backend)
        frontend = subprocess.Popen(
            [node, str(ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"),
             "--host", "127.0.0.1"],
            cwd=ROOT / "frontend",
            env=environment,
        )
        time.sleep(1)
        if frontend.poll() is not None:
            raise SystemExit("Frontend не запустился. Посмотрите сообщение выше.")
        print("\nKroika готова: http://127.0.0.1:5173")
        print("Для остановки нажмите Ctrl+C.\n")
        if open_browser:
            webbrowser.open("http://127.0.0.1:5173")
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nОстанавливаем Kroika…")
    finally:
        for process in (frontend, backend):
            if process is not None and process.poll() is None:
                process.terminate()
        for process in (frontend, backend):
            if process is not None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Первый запуск и старт Kroika")
    parser.add_argument("--setup-only", action="store_true", help="только установить зависимости")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    args = parser.parse_args()
    bootstrap()
    if not args.setup_only:
        run(open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
