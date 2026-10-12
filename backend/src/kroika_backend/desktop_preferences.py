"""Desktop preferences with OS credentials kept outside project/configuration files."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import UUID, uuid4

from .config import Settings


class PreferenceError(ValueError):
    pass


def desktop_home() -> Path:
    override = os.getenv("KROIKA_DESKTOP_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Kroika"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Kroika"
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "kroika"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class SystemVault:
    def __init__(self):
        self.backend = None
        try:
            if sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring
                backend = WinVaultKeyring()
            elif sys.platform == "darwin":
                from keyring.backends.macOS import Keyring
                backend = Keyring()
            else:
                from keyring.backends.SecretService import Keyring
                backend = Keyring()
            if backend.priority > 0:
                self.backend = backend
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self.backend is not None

    def get(self, service: str, key_id: str) -> str | None:
        if self.backend is None:
            return None
        try:
            return self.backend.get_password(service, key_id)
        except Exception:
            return None

    def set(self, service: str, key_id: str, key: str) -> None:
        if self.backend is None:
            raise PreferenceError("Системное хранилище ключей недоступно. Выберите ключ на сеанс.")
        try:
            self.backend.set_password(service, key_id, key)
        except Exception as error:
            raise PreferenceError("Не удалось сохранить ключ в системном хранилище.") from error

    def delete(self, service: str, key_id: str) -> bool:
        if self.backend is not None:
            try:
                self.backend.delete_password(service, key_id)
            except Exception:
                return False
        return True


class Preferences:
    FIELDS = {
        "provider", "model", "thinking", "timeout", "max_output_tokens", "api_mode", "attempts",
    }

    def __init__(self, home: Path, vault=None):
        self.home = home.resolve()
        self.path = self.home / "settings.json"
        self.vault = vault if vault is not None else SystemVault()
        identity = hashlib.sha256(os.path.normcase(str(self.home)).encode()).hexdigest()[:20]
        self.service = f"Kroika/Gemini/{identity}"
        self.document = {}
        self.cleanup_warning = False
        if self.path.exists():
            try:
                self.document = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(self.document, dict) or self.document.get("version") != 1
                        or not self.FIELDS <= set(self.document)
                        or set(self.document) - self.FIELDS - {"version", "key_mode", "key_id"}):
                    raise ValueError()
                if self.document.get("key_mode") not in {"system", "none", "session", "environment"}:
                    raise ValueError()
                if self.document.get("key_id"):
                    UUID(self.document["key_id"])
                if self.document["key_mode"] == "system" and not self.document.get("key_id"):
                    raise ValueError()
            except (OSError, ValueError, TypeError) as error:
                raise PreferenceError("Файл настроек приложения повреждён: settings.json.") from error

    @staticmethod
    def _values(settings: Settings) -> dict:
        return {
            "provider": settings.ai_provider, "model": settings.gemini_model,
            "thinking": settings.gemini_thinking_level, "timeout": settings.ai_timeout_seconds,
            "max_output_tokens": settings.gemini_max_output_tokens,
            "api_mode": settings.gemini_api_mode, "attempts": settings.ai_max_attempts,
        }

    @staticmethod
    def _apply(settings: Settings, values: dict, key: str | None) -> Settings:
        if set(values) != Preferences.FIELDS:
            raise PreferenceError("Заполните все настройки сервиса.")
        if (values["provider"] not in {"mock", "gemini", "qwen"}
                or not isinstance(values["model"], str) or not values["model"].strip()
                or len(values["model"]) > 100
                or any(character.isspace() for character in values["model"])):
            raise PreferenceError("Проверьте выбранный сервис и имя модели.")
        try:
            timeout = float(values["timeout"])
            tokens = int(values["max_output_tokens"])
            attempts = int(values["attempts"])
            if tokens != float(values["max_output_tokens"]) or attempts != float(values["attempts"]):
                raise ValueError()
        except (ValueError, TypeError, OverflowError) as error:
            raise PreferenceError("Время ожидания, токены и число попыток должны быть числами.") from error
        enabled = tuple(dict.fromkeys((*settings.enabled_ai_providers, "mock", "gemini",
                                       values["provider"])))
        candidate = replace(
            settings, ai_provider=values["provider"], enabled_ai_providers=enabled,
            gemini_model=values["model"].strip(), gemini_thinking_level=values["thinking"],
            gemini_api_mode=values["api_mode"], gemini_max_output_tokens=tokens,
            ai_timeout_seconds=timeout, ai_max_attempts=attempts, gemini_api_key=key,
        )
        try:
            candidate.validate()
        except ValueError as error:
            if values["thinking"] == "minimal":
                raise PreferenceError("Проверьте параметры. Если модель не поддерживает минимальное размышление, выберите автоматическое.") from error
            raise PreferenceError("Проверьте время ожидания, число попыток и параметры ответа модели.") from error
        return candidate

    def load(self, base: Settings) -> Settings:
        if not self.document:
            return base
        mode = self.document["key_mode"]
        key = base.gemini_api_key if mode == "environment" else None
        if mode == "system":
            key = self.vault.get(self.service, self.document["key_id"])
        return self._apply(base, {field: self.document[field] for field in self.FIELDS}, key)

    def describe(self, current: Settings) -> dict:
        from .desktop_version import VERSION, RELEASES_URL
        return {
            "app_version": VERSION, "packaged": bool(getattr(sys, "frozen", False)),
            "releases_url": RELEASES_URL,
            **self._values(current), "has_key": bool(current.gemini_api_key),
            "key_storage": self.document.get("key_mode", "environment")
            if current.gemini_api_key else "none",
            "secure_storage_available": self.vault.available,
            "key_cleanup_warning": self.cleanup_warning,
            "data_dir": str(current.database_path.parent),
            "images_dir": str(current.image_storage_path), "logs_dir": str(self.home / "logs"),
        }

    def prepare(self, payload: dict, current: Settings):
        if not isinstance(payload, dict) or set(payload) != self.FIELDS | {"key_action", "api_key", "remember"}:
            raise PreferenceError("Некорректные поля настроек.")
        action = payload["key_action"]
        if action not in {"keep", "set", "remove"} or not isinstance(payload["remember"], bool):
            raise PreferenceError("Выберите действие с API-ключом.")
        key = current.gemini_api_key
        mode = self.document.get("key_mode", "environment" if key else "none")
        key_id = self.document.get("key_id")
        if action == "set":
            if not isinstance(payload["api_key"], str):
                raise PreferenceError("Введите API-ключ.")
            key = payload["api_key"].strip()
            if not key or len(key) > 2048 or "\n" in key or "\r" in key:
                raise PreferenceError("Введите корректный API-ключ.")
            mode = "system" if payload["remember"] else "session"
            key_id = str(uuid4()) if mode == "system" else None
        elif action == "remove":
            key, mode, key_id = None, "none", None
        candidate = self._apply(current, {field: payload[field] for field in self.FIELDS}, key)
        document = {**self._values(candidate), "version": 1, "key_mode": mode}
        if key_id:
            document["key_id"] = key_id
        return candidate, document

    def commit(self, candidate: Settings, document: dict) -> None:
        old_id = self.document.get("key_id")
        new_id = document.get("key_id")
        try:
            if new_id and new_id != old_id:
                self.vault.set(self.service, new_id, candidate.gemini_api_key)
            atomic_json(self.path, document)
        except Exception:
            if new_id and new_id != old_id:
                self.vault.delete(self.service, new_id)
            raise
        self.document = document
        self.cleanup_warning = False
        if old_id and old_id != new_id:
            self.cleanup_warning = self.vault.delete(self.service, old_id) is False
