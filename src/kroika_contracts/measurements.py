"""Versioned measurement catalogue and fail-closed validation rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

from .contract_io import validate_document

CATALOG_VERSION = "1.0.0"
GarmentType = Literal[
    "dress", "sundress", "skirt", "top", "blouse", "shirt", "vest",
    "jacket", "trousers", "shorts", "jumpsuit",
]

UPPER = ("dress", "sundress", "top", "blouse", "shirt", "vest", "jacket", "jumpsuit")
LOWER = ("dress", "sundress", "skirt", "trousers", "shorts", "jumpsuit")
ALL = tuple(dict.fromkeys((*UPPER, *LOWER)))
STAGE12_UPPER = ("dress", "sundress", "top", "blouse", "shirt", "vest")
STAGE13_UPPER = (*STAGE12_UPPER, "jacket")
STAGE12_ALL = (*STAGE12_UPPER, "skirt")
STAGE13_ALL = (*STAGE13_UPPER, "skirt")
STAGE14_LOWER = ("trousers", "shorts")
STAGE14_ALL = (*STAGE13_ALL, *STAGE14_LOWER)


@dataclass(frozen=True, slots=True)
class MeasurementDefinition:
    id: str
    label_ru: str
    group: str
    kind: Literal["linear", "angle"]
    unit: Literal["mm", "deg"]
    minimum: float
    maximum: float
    instruction_ru: str
    illustration: str
    applicable_to: tuple[str, ...]
    required_for: tuple[str, ...] = ()
    sleeve_only: bool = False


@dataclass(frozen=True, slots=True)
class MeasurementIssue:
    code: str
    severity: Literal["blocking_error", "warning"]
    json_pointer: str
    message_ru: str


def _linear(
    id: str, label: str, group: str, minimum: float, maximum: float,
    instruction: str, illustration: str, applicable: tuple[str, ...],
    required: tuple[str, ...] = (), *, sleeve_only: bool = False,
) -> MeasurementDefinition:
    return MeasurementDefinition(
        id, label, group, "linear", "mm", minimum, maximum, instruction,
        illustration, applicable, required, sleeve_only,
    )


MEASUREMENTS: tuple[MeasurementDefinition, ...] = (
    _linear("height", "Рост", "Основные", 1200, 2100,
            "Встаньте без обуви у стены. Измерьте вертикально от пола до макушки.",
            "height", ALL),
    _linear("bust", "Обхват груди", "Обхваты", 600, 1800,
            "Лента проходит горизонтально через выступающие точки груди и лопатки, без затягивания.",
            "bust", UPPER, STAGE13_UPPER),
    _linear("waist", "Обхват талии", "Обхваты", 450, 1700,
            "Повяжите установочную ленту по естественной талии и измерьте вокруг неё без натяжения.",
            "waist", ALL, STAGE14_ALL),
    _linear("hips", "Обхват бёдер", "Обхваты", 650, 1900,
            "Измерьте горизонтально вокруг наиболее выступающих точек ягодиц и бёдер.",
            "hips", ALL, STAGE14_ALL),
    _linear("neck_circumference", "Обхват шеи", "Обхваты", 250, 650,
            "Проведите ленту по основанию шеи через седьмой шейный позвонок и яремную впадину.",
            "neck", UPPER, ("shirt", "jacket")),
    _linear("chest_width", "Ширина груди", "Ширины", 220, 600,
            "Измерьте спереди между передними углами подмышечных впадин над основанием груди.",
            "front-width", UPPER),
    _linear("back_width", "Ширина спины", "Ширины", 250, 650,
            "Измерьте горизонтально по лопаткам между задними углами подмышечных впадин.",
            "back-width", UPPER),
    _linear("back_bust_arc", "Задняя дуга груди", "Дуги", 250, 1100,
            "От одной согласованной боковой вертикали до другой проведите ленту по спинке на уровне груди.",
            "back-arc", UPPER, STAGE13_UPPER),
    _linear("back_waist_arc", "Задняя дуга талии", "Дуги", 180, 850,
            "Измерьте по спинке между теми же боковыми вертикалями на установочной ленте талии.",
            "back-arc", ALL, STAGE13_ALL),
    _linear("back_hip_arc", "Задняя дуга бёдер", "Дуги", 250, 1000,
            "Измерьте по спинке между теми же боковыми вертикалями на уровне бёдер.",
            "back-arc", ALL, STAGE13_ALL),
    _linear("shoulder_span", "Плечевой обхват", "Плечо и баланс", 280, 650,
            "Измерьте вокруг плечевого пояса по уровню, принятому в выбранной методике.",
            "shoulder", UPPER, STAGE13_UPPER),
    _linear("shoulder_length", "Длина плеча", "Плечо и баланс", 80, 220,
            "От основания шеи проведите ленту до плечевой точки по середине плеча.",
            "shoulder", UPPER, STAGE13_UPPER),
    _linear("back_neck_to_waist", "Длина спины до талии", "Длины корпуса", 300, 650,
            "От седьмого шейного позвонка измерьте по позвоночнику до установочной ленты талии.",
            "back-length", UPPER, STAGE13_UPPER),
    _linear("front_neck_to_waist_over_bust", "Длина переда до талии", "Длины корпуса", 320, 750,
            "От основания шеи проведите ленту через выступающую точку груди до талии.",
            "front-length", UPPER, STAGE13_UPPER),
    _linear("bust_path_height", "Высота линии груди", "Грудь", 150, 450,
            "Снимите расстояние от плечевого уровня до линии груди по правилу выбранной методики.",
            "bust-height", UPPER, STAGE13_UPPER),
    _linear("bust_vertical_height", "Высота груди", "Грудь", 140, 400,
            "От основания шеи измерьте до выступающей точки груди по вертикальному направлению методики.",
            "bust-height", UPPER, STAGE13_UPPER),
    _linear("bust_span", "Расстояние между центрами груди", "Грудь", 100, 350,
            "Измерьте горизонтально между выступающими точками груди.",
            "bust-span", UPPER, STAGE13_UPPER),
    _linear("hip_depth", "Высота бёдер", "Длины корпуса", 120, 400,
            "Измерьте вертикально от установочной ленты талии до линии бёдер сбоку.",
            "hip-depth", ALL, STAGE13_ALL),
    _linear("armscye_depth", "Глубина проймы", "Длины корпуса", 140, 400,
            "Измерьте вертикально от плечевого уровня до горизонтали подмышечных впадин.",
            "armscye", UPPER, STAGE13_UPPER),
    _linear("upper_arm_circumference", "Обхват плеча", "Рукав", 180, 700,
            "Измерьте вокруг самой полной части верхней части руки, рука свободно опущена.",
            "arm", UPPER, sleeve_only=True),
    _linear("wrist_circumference", "Обхват запястья", "Рукав", 120, 350,
            "Измерьте вокруг запястья через выступающие косточки без прибавки.",
            "wrist", UPPER, sleeve_only=True),
    _linear("hand_circumference", "Обхват кисти", "Рукав", 150, 400,
            "Сложите большой палец к ладони и измерьте наиболее широкую часть кисти.",
            "wrist", UPPER, sleeve_only=True),
    _linear("sleeve_length", "Длина рукава", "Рукав", 250, 900,
            "От плечевой точки измерьте по слегка согнутой руке до желаемого уровня рукава.",
            "arm", UPPER, sleeve_only=True),
    _linear("elbow_circumference", "Обхват локтя", "Рукав", 180, 600,
            "Измерьте вокруг слегка согнутого локтя в наиболее широкой части.",
            "elbow", UPPER, sleeve_only=True),
    _linear("elbow_length", "Длина до локтя", "Рукав", 150, 500,
            "От плечевой точки измерьте по руке до выступа локтя.",
            "elbow", UPPER, sleeve_only=True),
    _linear("front_diagonal_shoulder_height", "Косая высота плеча спереди", "Плечо и баланс", 250, 650,
            "Контрольную диагональ снимайте только по точкам, закреплённым выбранной методикой.",
            "shoulder-diagonal", ("jacket",), ("jacket",)),
    _linear("back_diagonal_shoulder_height", "Косая высота плеча сзади", "Плечо и баланс", 250, 650,
            "Контрольную диагональ снимайте только по точкам, закреплённым выбранной методикой.",
            "shoulder-diagonal", ("jacket",), ("jacket",)),
    _linear("sitting_height", "Высота сидения", "Брюки", 180, 420,
            "Сидя на ровной поверхности измерьте вертикально от талии сбоку до поверхности сиденья.",
            "trousers", ("trousers", "shorts", "jumpsuit"),
            ("trousers", "shorts", "jumpsuit")),
    _linear("crotch_length", "Дуга сидения", "Брюки", 450, 1000,
            "Проведите ленту от талии спереди через пах до талии сзади, без натяжения.",
            "trousers", ("trousers", "shorts", "jumpsuit"),
            ("trousers", "shorts", "jumpsuit")),
    _linear("outside_leg_length", "Длина по боку", "Брюки", 650, 1250,
            "От уровня талии измерьте вертикально по боку до пола или выбранной длины.",
            "trousers", ("trousers", "shorts", "jumpsuit"),
            ("trousers", "shorts", "jumpsuit")),
    _linear("inseam_length", "Шаговая длина", "Брюки", 350, 950,
            "Измерьте от паха по внутренней стороне ноги до пола или выбранного уровня.",
            "trousers", ("trousers", "shorts", "jumpsuit"),
            ("trousers", "shorts", "jumpsuit")),
    _linear("thigh_circumference", "Обхват бедра ноги", "Брюки", 300, 1000,
            "Измерьте горизонтально вокруг наиболее полной части верхней части ноги.",
            "trousers", ("trousers", "shorts", "jumpsuit"),
            ("trousers", "shorts", "jumpsuit")),
    _linear("knee_circumference", "Обхват колена", "Брюки", 220, 700,
            "Измерьте вокруг колена при положении ноги, принятом для выбранной методики.",
            "trousers", ("trousers", "jumpsuit"), ("trousers", "jumpsuit")),
    _linear("trouser_hem_circumference", "Обхват низа брючины", "Брюки", 180, 800,
            "Укажите желаемый готовый обхват одной брючины по линии низа.",
            "trousers", ("trousers", "jumpsuit"), ("trousers", "jumpsuit")),
    _linear("knee_height", "Высота колена", "Брюки", 300, 750,
            "Измерьте вертикально от пола до уровня центра колена.",
            "trousers", ("trousers", "jumpsuit"), ("trousers", "jumpsuit")),
    MeasurementDefinition(
        "shoulder_slope", "Наклон плеча", "Плечо и баланс", "angle", "deg", 0, 40,
        "Угол измеряйте инструментом либо получайте только по явно указанной формуле методики.",
        "shoulder-angle", UPPER, STAGE13_UPPER,
    ),
    MeasurementDefinition(
        "hip_inclination", "Наклон линии бёдер", "Плечо и баланс", "angle", "deg", 0, 40,
        "Угол измеряйте инструментом либо получайте только по явно указанной формуле методики.",
        "hip-angle", ALL, STAGE13_ALL,
    ),
)

BY_ID = {item.id: item for item in MEASUREMENTS}


def required_ids(garment_type: str, sleeve_type: str = "sleeveless") -> tuple[str, ...]:
    return tuple(
        item.id for item in MEASUREMENTS
        if garment_type in item.required_for
        or (item.sleeve_only and garment_type in item.applicable_to and sleeve_type != "sleeveless")
    )


def catalogue(garment_type: str, sleeve_type: str = "sleeveless") -> dict[str, Any]:
    required = set(required_ids(garment_type, sleeve_type))
    definitions = []
    for item in MEASUREMENTS:
        if garment_type not in item.applicable_to or (item.sleeve_only and sleeve_type == "sleeveless"):
            continue
        public = asdict(item)
        public["required"] = item.id in required
        public["applicable_to"] = list(item.applicable_to)
        public["required_for"] = list(item.required_for)
        definitions.append(public)
    return {
        "schema_version": "1.0.0",
        "catalog_version": CATALOG_VERSION,
        "garment_type": garment_type,
        "sleeve_type": sleeve_type,
        "normalized_unit": "mm",
        "display_units": ["cm", "mm"],
        "source_options": ["user", "preset", "derived"],
        "measurements": definitions,
    }


def measurement_issues(
    measurements: Mapping[str, Any], garment_type: str | None = None,
    sleeve_type: str = "sleeveless",
) -> list[MeasurementIssue]:
    issues: list[MeasurementIssue] = []
    values = measurements.get("values", {})
    angles = measurements.get("angles_deg", {})

    for name, measurement in values.items():
        definition = BY_ID.get(name)
        if definition is None:
            continue
        value = measurement["value"]
        pointer = f"/body_measurements/values/{name}"
        if not definition.minimum <= value <= definition.maximum:
            issues.append(MeasurementIssue(
                "MEASUREMENT_OUT_OF_RANGE", "blocking_error", pointer,
                f"«{definition.label_ru}»: проверьте значение — допустимый рабочий диапазон "
                f"{definition.minimum:g}–{definition.maximum:g} {definition.unit}.",
            ))
        original = measurement.get("original_input")
        if original is not None:
            expected_mm = original["value"] * (10 if original["unit"] == "cm" else 1)
            if abs(value - expected_mm) > 1e-9:
                issues.append(MeasurementIssue(
                    "NORMALIZATION_MISMATCH", "blocking_error", f"{pointer}/value",
                    "Значение в миллиметрах не совпадает с исходным вводом.",
                ))

    for name, value in angles.items():
        definition = BY_ID.get(name)
        if definition and not definition.minimum <= value <= definition.maximum:
            issues.append(MeasurementIssue(
                "MEASUREMENT_OUT_OF_RANGE", "blocking_error",
                f"/body_measurements/angles_deg/{name}",
                f"«{definition.label_ru}»: проверьте угол — допустимый рабочий диапазон "
                f"{definition.minimum:g}–{definition.maximum:g}°.",
            ))

    if measurements.get("status") == "ready" and garment_type:
        for name in required_ids(garment_type, sleeve_type):
            definition = BY_ID[name]
            present = name in (angles if definition.kind == "angle" else values)
            if not present:
                area = "angles_deg" if definition.kind == "angle" else "values"
                issues.append(MeasurementIssue(
                    "MEASUREMENT_REQUIRED", "blocking_error",
                    f"/body_measurements/{area}/{name}",
                    f"Для этого изделия нужна мерка «{definition.label_ru}».",
                ))

    for arc, circumference in (
        ("back_bust_arc", "bust"), ("back_waist_arc", "waist"), ("back_hip_arc", "hips")
    ):
        if arc in values and circumference in values:
            if values[arc]["value"] >= values[circumference]["value"]:
                issues.append(MeasurementIssue(
                    "MEASUREMENT_ARC_NOT_SMALLER", "blocking_error",
                    f"/body_measurements/values/{arc}",
                    "Задняя дуга должна быть меньше соответствующего полного обхвата.",
                ))

    for shorter, longer, message in (
        ("elbow_length", "sleeve_length", "Длина до локтя должна быть меньше полной длины рукава."),
        ("inseam_length", "outside_leg_length", "Шаговая длина должна быть меньше длины по боку."),
        ("knee_height", "outside_leg_length", "Высота колена должна быть меньше длины по боку."),
    ):
        if shorter in values and longer in values and values[shorter]["value"] >= values[longer]["value"]:
            issues.append(MeasurementIssue(
                "MEASUREMENT_LENGTH_ORDER", "blocking_error",
                f"/body_measurements/values/{shorter}", message,
            ))
    if "wrist_circumference" in values and "hand_circumference" in values:
        if values["wrist_circumference"]["value"] >= values["hand_circumference"]["value"]:
            issues.append(MeasurementIssue(
                "MEASUREMENT_CIRCUMFERENCE_ORDER", "warning",
                "/body_measurements/values/hand_circumference",
                "Перепроверьте обхват кисти: обычно он больше обхвата запястья.",
            ))
    return issues


def validate_measurement_profile(
    measurements: Mapping[str, Any], garment_type: str | None = None,
    sleeve_type: str = "sleeveless",
) -> None:
    validate_document("body-measurements", measurements)
    blocking = [
        item for item in measurement_issues(measurements, garment_type, sleeve_type)
        if item.severity == "blocking_error"
    ]
    if blocking:
        from .semantic import SemanticContractError, SemanticIssue

        raise SemanticContractError([
            SemanticIssue(item.code, item.json_pointer, item.message_ru) for item in blocking
        ])
