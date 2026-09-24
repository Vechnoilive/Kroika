"""Cross-platform helpers shared by stage verification scripts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
import shutil


_NPM_EXECUTABLE_NAME = "npm.cmd" if os.name == "nt" else "npm"


def resolve_command(
    command: Sequence[str],
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    """Resolve Windows command shims before passing them to subprocess."""
    resolved = list(command)
    if not resolved or resolved[0] != "npm":
        return resolved

    search_path = environment.get("PATH") if environment is not None else None
    executable = shutil.which(_NPM_EXECUTABLE_NAME, path=search_path)
    if executable is None:
        raise SystemExit(
            "Для frontend-проверок нужен Node.js 24 с npm в PATH. "
            "После установки Node.js откройте новую консоль."
        )
    resolved[0] = executable
    return resolved
