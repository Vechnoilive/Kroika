"""Load and validate the version-controlled JSON contracts."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / 'schemas'


class ContractValidationError(ValueError):
    """A document does not match its declared JSON contract."""

    def __init__(self, schema_name: str, errors: list[str]):
        self.schema_name = schema_name
        self.errors = tuple(errors)
        super().__init__(f'{schema_name}: ' + '; '.join(errors))


def available_schemas(version: str = 'v1') -> tuple[str, ...]:
    directory = SCHEMA_ROOT / version
    if not directory.is_dir():
        raise ValueError(f'Unknown schema version: {version}')
    return tuple(sorted(path.name.removesuffix('.schema.json')
                        for path in directory.glob('*.schema.json')))


def load_schema(name: str, version: str = 'v1') -> dict[str, Any]:
    if name not in available_schemas(version):
        raise ValueError(f'Unknown schema: {version}/{name}')
    return json.loads((SCHEMA_ROOT / version / f'{name}.schema.json').read_text(encoding='utf-8'))


def schema_registry(version: str = 'v1') -> Registry:
    resources = []
    for name in available_schemas(version):
        schema = load_schema(name, version)
        resources.append((schema['$id'], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _json_pointer(error) -> str:
    if not error.absolute_path:
        return '/'
    escaped = [str(part).replace('~', '~0').replace('/', '~1')
               for part in error.absolute_path]
    return '/' + '/'.join(escaped)


def validation_errors(name: str, document: Any, version: str = 'v1') -> tuple[str, ...]:
    schema = load_schema(name, version)
    validator = Draft202012Validator(
        schema,
        registry=schema_registry(version),
        format_checker=FormatChecker(),
    )
    errors = [f'{_json_pointer(error)}: {error.message}'
              for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path))]

    def reject_nonfinite(value: Any, pointer: str = '') -> None:
        if isinstance(value, float) and not math.isfinite(value):
            errors.append(f'{pointer or "/"}: non-finite JSON number is forbidden')
        elif isinstance(value, dict):
            for key, item in value.items():
                token = str(key).replace('~', '~0').replace('/', '~1')
                reject_nonfinite(item, f'{pointer}/{token}')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                reject_nonfinite(item, f'{pointer}/{index}')

    reject_nonfinite(document)
    return tuple(errors)


def validate_document(name: str, document: Any, version: str = 'v1') -> None:
    errors = validation_errors(name, document, version)
    if errors:
        raise ContractValidationError(name, list(errors))
