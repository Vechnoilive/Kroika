"""Explicit, non-destructive PatternProject migration registry."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping

LATEST_PROJECT_VERSION = '1.0.0'
Migration = Callable[[dict[str, Any]], dict[str, Any]]


class UnsupportedProjectVersion(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MigrationStep:
    target_version: str
    migrate: Migration


class MigrationRegistry:
    def __init__(self, latest_version: str, steps: Mapping[str, MigrationStep] | None = None):
        self.latest_version = latest_version
        self._steps = dict(steps or {})

    def migrate(self, project: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(project, Mapping):
            raise UnsupportedProjectVersion('Файл проекта должен содержать JSON-объект.')
        version = project.get('schema_version')
        if not isinstance(version, str):
            raise UnsupportedProjectVersion(
                'В проекте отсутствует schema_version; автоматическая догадка запрещена.')
        migrated = deepcopy(dict(project))
        visited: set[str] = set()
        while version != self.latest_version:
            if version in visited:
                raise RuntimeError(f'Цикл в реестре миграций: {version}')
            visited.add(version)
            step = self._steps.get(version)
            if step is None:
                raise UnsupportedProjectVersion(
                    f'Нет проверенного пути миграции {version} → {self.latest_version}. '
                    'Исходный файл не изменён.')
            migrated = step.migrate(deepcopy(migrated))
            if migrated.get('schema_version') != step.target_version:
                raise RuntimeError(
                    f'Миграция {version} не установила {step.target_version}.')
            version = step.target_version
        return migrated


# 1.0.0 is the first released PatternProject contract. There is no honest
# pre-v1 project format to guess from, so the production registry starts empty.
PROJECT_MIGRATIONS = MigrationRegistry(LATEST_PROJECT_VERSION)


def migrate_project(project: Mapping[str, Any]) -> dict[str, Any]:
    return PROJECT_MIGRATIONS.migrate(project)
