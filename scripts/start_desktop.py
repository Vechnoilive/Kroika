#!/usr/bin/env python3
"""Build the existing interface and start it in its own desktop window."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

try:
    from . import start_local
except ImportError:
    import start_local


ROOT = start_local.ROOT
STATE = start_local.STATE / "desktop"


def frontend_fingerprint() -> str:
    frontend = ROOT / "frontend"
    files = [frontend / "index.html", frontend / "package.json", frontend / "package-lock.json",
             frontend / "vite.config.ts", *frontend.glob("tsconfig*.json")]
    for directory in (frontend / "src", frontend / "public"):
        files.extend(path for path in directory.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(frontend).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_desktop(*, rebuild: bool = False) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    requirements = ROOT / "requirements-desktop.txt"
    dependency_hash = hashlib.sha256(requirements.read_bytes()).hexdigest()
    dependency_stamp = STATE / "dependencies.sha256"
    if (not dependency_stamp.is_file()
            or dependency_stamp.read_text(encoding="utf-8").strip() != dependency_hash):
        print("Устанавливаем компонент окна Кройки…", flush=True)
        subprocess.run(
            [str(start_local._venv_python()), "-m", "pip", "install", "-r", str(requirements)],
            cwd=ROOT, check=True,
        )
        dependency_stamp.write_text(dependency_hash + "\n", encoding="utf-8")

    fingerprint = frontend_fingerprint()
    build_stamp = STATE / "frontend.sha256"
    if (rebuild or not (ROOT / "frontend" / "dist" / "index.html").is_file()
            or not build_stamp.is_file()
            or build_stamp.read_text(encoding="utf-8").strip() != fingerprint):
        print("Собираем интерфейс Кройки…", flush=True)
        # Invalidate the stamp before building, so an interrupted build is never reused.
        build_stamp.unlink(missing_ok=True)
        subprocess.run([start_local._npm(), "run", "build"], cwd=ROOT / "frontend", check=True)
        build_stamp.write_text(fingerprint + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Первый запуск Кройки в отдельном окне")
    parser.add_argument("--setup-only", action="store_true", help="подготовить без открытия окна")
    parser.add_argument("--rebuild", action="store_true", help="пересобрать интерфейс")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--data-dir", type=Path, help="папка проектов и изображений")
    parser.add_argument("--debug", action="store_true", help="открыть инструменты разработчика")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port должен быть от 1 до 65535")
    try:
        start_local.bootstrap()
        prepare_desktop(rebuild=args.rebuild)
        if args.setup_only:
            return 0
        command = [str(start_local._venv_python()), "-m", "kroika_backend.desktop",
                   "--frontend-dir", str(ROOT / "frontend" / "dist"),
                   "--port", str(args.port)]
        if args.data_dir:
            command.extend(["--data-dir", str(args.data_dir.expanduser().resolve())])
        if args.debug:
            command.append("--debug")
        print("Открываем Кройку…", flush=True)
        # Replace the bootstrap launcher: the window directly owns its backend process.
        os.chdir(ROOT)
        os.execve(command[0], command, os.environ.copy())
        return 0
    except KeyboardInterrupt:
        return 0
    except subprocess.CalledProcessError:
        print("Подготовка приложения не завершена. Исправьте ошибку выше и повторите запуск.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
