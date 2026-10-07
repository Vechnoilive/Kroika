#!/usr/bin/env python3
"""Compare Gemini text-only probes without starting the web app or sending images."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "backend/src")]

from kroika_backend.config import Settings  # noqa: E402
from kroika_backend.image_store import LocalImageStore  # noqa: E402
from kroika_backend.vision_providers import GeminiProvider  # noqa: E402
from kroika_contracts.ports import AIProviderError  # noqa: E402


async def check_models(models: list[str], modes: list[str]) -> int:
    settings = Settings.from_env()
    settings.validate()
    if not settings.gemini_api_key:
        print("Задайте GEMINI_API_KEY в этой консоли. Ключ не выводится.")
        return 2
    print("Проверка отправляет только короткий текст OK. Фото и мерки не используются.")
    print("На каждую комбинацию модели и API выполняется один запрос, без повторов.")
    successes = 0
    with TemporaryDirectory(prefix="kroika-gemini-check-") as directory:
        for model in models:
            for mode in modes:
                adapter = GeminiProvider(
                    image_store=LocalImageStore(Path(directory) / "images"),
                    api_key=settings.gemini_api_key, base_url=settings.gemini_base_url,
                    model=model, api_mode=mode, timeout_seconds=30, max_attempts=1,
                )
                started = perf_counter()
                try:
                    await adapter.check_connection()
                    successes += 1
                    result = "OK"
                except AIProviderError as exc:
                    result = f"{exc.code.value.upper()}: {exc.message_ru}"
                print(f"{model} | {mode} | {perf_counter() - started:.1f} сек. | {result}")
    print("OK проверяет доступ к модели, но не точность распознавания одежды.")
    return 0 if successes else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=[
        "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
    ])
    parser.add_argument("--api-modes", nargs="+", choices=["generate_content", "interactions"],
                        default=["generate_content", "interactions"])
    arguments = parser.parse_args()
    return asyncio.run(check_models(arguments.models, arguments.api_modes))


if __name__ == "__main__":
    raise SystemExit(main())
