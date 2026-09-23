"""Shared, provider-neutral garment analysis instructions and output schema."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from kroika_contracts.contract_io import load_schema


COMMON_SYSTEM_PROMPT = """Ты — ассистент конструктора одежды Kroika.
Анализируй только видимые конструктивные признаки одежды на приложенных изображениях.
Никогда не оценивай и не выдумывай мерки тела, размеры, длины в сантиметрах, координаты
выкройки, припуски или скрытые элементы. Не идентифицируй человека.
Отдельно перечисляй все видимые конструктивные и декоративные элементы: пояса, складки,
защипы, сборки, воланы, оборки, кокетки, панели, накладные слои, драпировки, карманы,
застёжки, разрезы, воротники, манжеты и другие детали. Для каждого элемента указывай
место, способ соединения, доказательство на изображении и необходимость подтверждения.
Слои основной ткани, подкладки, прокладки и прозрачного наложения описывай раздельно.
Используй только переданные допустимые категории и значения признаков. Если деталь не
видна или уверенность недостаточна, выбери unknown/uncertain, понизь confidence,
добавь понятную неопределённость и один точный вопрос пользователю. Все пояснения и
вопросы пиши по-русски. Верни только один JSON-объект без Markdown и служебного текста.
"""


def _resolve_schema_node(node: Any, root: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_resolve_schema_node(item, root) for item in node]
    if not isinstance(node, dict):
        return node
    reference = node.get("$ref")
    if reference:
        if reference == "common.schema.json#/$defs/schema_version":
            return {"type": "string", "enum": ["1.0.0"]}
        if reference.startswith("#/$defs/"):
            name = reference.rsplit("/", 1)[-1]
            return _resolve_schema_node(deepcopy(root["$defs"][name]), root)
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in {"$schema", "$id", "$defs", "uniqueItems"}:
            continue
        if key == "const":
            result["enum"] = [value]
            continue
        result[key] = _resolve_schema_node(value, root)
    return result


def provider_analysis_schema() -> dict[str, Any]:
    schema = load_schema("ai-style-analysis")
    provider_schema = _resolve_schema_node(schema, schema)
    # Canonical storage keeps this field optional so projects saved before stage 16
    # remain readable. Every new provider response must include the richer plan.
    provider_schema["required"] = [*provider_schema["required"], "design_features"]
    return provider_schema


def analysis_instruction(
    supported_categories: list[str],
    supported_features: dict[str, list[str]],
    image_views: list[str] | None = None,
) -> str:
    allowed = json.dumps(
        {"supported_garment_categories": supported_categories, "supported_features": supported_features},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    view_hint = ""
    if image_views:
        ordered_views = [
            {"image_number": index, "view": view}
            for index, view in enumerate(image_views, start=1)
        ]
        view_hint = (
            " Пользователь подписал изображения в порядке передачи: "
            + json.dumps(ordered_views, ensure_ascii=False, separators=(",", ":"))
            + ". Используй подписи как контекст, но не выдумывай невидимые детали."
        )
    return (
        "Определи фасон и полный набор видимых деталей по изображениям. "
        "design_features обязателен: elements содержит каждую отдельную деталь, layers — "
        "основной, накладные и остальные дополнительные слои, proportions — только "
        "визуальные категории без сантиметров. "
        "Не объединяй несколько разных деталей в один element."
        + view_hint
        + " Допустимый словарь: " + allowed
        + "\nОтвет обязан соответствовать этой JSON Schema: "
        + json.dumps(provider_analysis_schema(), ensure_ascii=False, separators=(",", ":"))
    )
