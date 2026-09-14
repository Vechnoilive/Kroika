# Реестр формул — этап 2

Всего **41** скалярных записей. Версия `0.1.0`, статус `experimental`; применение в production у каждой записи запрещено до проверки. Это полный реестр **внесённых скалярных выражений**, а не полный набор геометрических формул готового платья.

Канонические метаданные (единицы каждого входа, происхождение, версия, допуск, контрольные примеры, статус экспертной проверки): [formula-registry.json](../references/stage2/formula-registry.json). Одинаковые правила источника и области приведены в [PATTERN_METHOD.md](PATTERN_METHOD.md).

Формулы проверяются в указанном порядке. В выражениях все длины — mm; `radians` переводит deg → rad; `tan`, коэффициенты и дроби безразмерны. Ветка F19 использует порог **40 mm**, то есть 4 cm исходника. Эмпирические коэффициенты не являются производными мерками тела.

| ID | Назначение | Выражение → результат | Единица |
| --- | --- | --- | --- |
| F01 | Тангенс наклона плеча | `tan(radians(shoulder_slope_deg))` → `shoulder_tan` | 1 |
| F02 | Полуугол бока по исходному правилу | `tan(radians(hip_inclination_deg / 2))` → `hip_tan` | 1 |
| F03 | Ширина половины переда | `(bust - back_bust_arc) / 2` → `front_width` | mm |
| F04 | Ширина половины спинки | `back_bust_arc / 2` → `back_width` | mm |
| F05 | Целевая половина передней дуги талии | `(waist - back_waist_arc) / 2` → `front_waist` | mm |
| F06 | Целевая половина задней дуги талии | `back_waist_arc / 2` → `back_waist` | mm |
| F07 | Взвешенная высота по правилу upstream, не новая снятая мерка | `(2 * bust_vertical_height + bust_path_height) / 3` → `bust_level` | mm |
| F08 | Конструктивный уровень груди от талии | `back_neck_to_waist - bust_level` → `bust_from_waist` | mm |
| F09 | Поправка наклона переда | `shoulder_tan * (front_width - shoulder_span / 2)` → `front_adjustment` | mm |
| F10 | Поправка наклона спинки | `shoulder_tan * (back_width - shoulder_span / 2)` → `back_adjustment` | mm |
| F11 | Длина заготовки переда | `front_neck_to_waist_over_bust - front_adjustment` → `front_max_length` | mm |
| F12 | Длина заготовки спинки | `back_neck_to_waist - back_adjustment` → `back_length` | mm |
| F13 | Исходная длина бока до закрытия вытачки и проверки кривых | `back_length - shoulder_tan * (front_width - back_width)` → `front_side_target` | mm |
| F14 | Раствор боковой нагрудной вытачки | `front_max_length - front_side_target` → `side_dart_width` | mm |
| F15 | Глубина боковой вытачки | `side_dart_depth_factor * (front_width - bust_span / 2)` → `side_dart_depth` | mm |
| F16 | Раствор талиевой вытачки переда | `(front_width - front_waist) * front_dart_fraction` → `front_waist_dart` | mm |
| F17 | Глубина талиевой вытачки переда | `dart_tip_factor * bust_from_waist` → `front_waist_dart_depth` | mm |
| F18 | Суммарное уменьшение ширины спинки | `back_width - back_waist` → `back_reduction` | mm |
| F19 | Уменьшение у бокового среза: точная ветка порога 40 мм | `0 if back_reduction < back_dart_threshold else back_reduction / 6` → `back_side_take` | mm |
| F20 | Раствор каждой из двух вытачек половины спинки | `(back_reduction - back_side_take) / 2` → `back_each_dart` | mm |
| F21 | Глубина длинной вытачки спинки | `back_length - bust_level` → `back_dart_depth` | mm |
| F22 | Глубина короткой вытачки спинки | `dart_tip_factor * back_dart_depth` → `back_short_dart_depth` | mm |
| F23 | Четвертная передняя доля бёдер для панели юбки | `(hips - back_hip_arc) / 2` → `skirt_front_hip` | mm |
| F24 | Четвертная задняя доля бёдер | `back_hip_arc / 2` → `skirt_back_hip` | mm |
| F25 | Исходная задняя глубина с коэффициентом 1.05 | `hip_depth * back_hip_factor` → `skirt_back_depth` | mm |
| F26 | Заужение переда у бокового шва юбки | `min(hip_tan * hip_depth, skirt_front_hip - front_waist)` → `skirt_front_side_take` | mm |
| F27 | Заужение спинки у бокового шва юбки | `min(hip_tan * skirt_back_depth, skirt_back_hip - back_waist)` → `skirt_back_side_take` | mm |
| F28 | Передняя вытачка на четверть юбки | `skirt_front_hip - front_waist - skirt_front_side_take` → `skirt_front_dart` | mm |
| F29 | Сумма двух задних вытачек на четверть юбки | `skirt_back_hip - back_waist - skirt_back_side_take` → `skirt_back_dart_total` | mm |
| F30 | Одна из двух задних вытачек | `skirt_back_dart_total / 2` → `skirt_back_each_dart` | mm |
| F31 | Глубина передней вытачки юбки | `hip_depth * 0.8` → `skirt_front_dart_depth` | mm |
| F32 | Глубина задней вытачки с поправкой длины | `hip_depth * 0.85 - (hip_depth - skirt_back_depth)` → `skirt_back_dart_depth` | mm |
| F33 | Конструктивная глубина, добавка 2.5 cm = 25 mm | `armscye_depth + armhole_ease` → `armhole_depth` | mm |
| F34 | Опорный размах рукава, уменьшение 2 cm = 20 mm | `shoulder_span - sleeve_balance_reduction` → `sleeve_balance` | mm |
| F35 | Контроль суммы целевых долей талии; не длина кривой | `2 * (front_waist + back_waist)` → `waist_projection` | mm |
| F36 | Контроль суммы долей бёдер | `2 * (skirt_front_hip + skirt_back_hip)` → `hip_projection` | mm |
| F37 | Контроль передней талии после исключения растворов | `2 * (skirt_front_hip - skirt_front_side_take - skirt_front_dart)` → `skirt_front_waist` | mm |
| F38 | Контроль задней талии после исключения растворов | `2 * (skirt_back_hip - skirt_back_side_take - skirt_back_dart_total)` → `skirt_back_waist` | mm |
| F39 | Явная разница глубин, которую нельзя скрывать при стачивании | `skirt_back_depth - hip_depth` → `back_hip_extension` | mm |
| F40 | Длина стороны симметричной треугольной вытачки | `sqrt((front_waist_dart / 2) ** 2 + front_waist_dart_depth ** 2)` → `front_waist_dart_leg` | mm |
| F41 | Длина стороны боковой треугольной вытачки | `sqrt((side_dart_width / 2) ** 2 + side_dart_depth ** 2)` → `side_dart_leg` | mm |

## Явные постоянные

| Имя | Значение | Происхождение |
| --- | --- | --- |
| `armhole_ease` | 25 mm | Зафиксированное правило исходного GarmentCode; не скрытая мерка |
| `sleeve_balance_reduction` | 20 mm | Зафиксированное правило исходного GarmentCode; не скрытая мерка |
| `back_dart_threshold` | 40 mm | Зафиксированное правило исходного GarmentCode; не скрытая мерка |
| `back_hip_factor` | 1.05 1 | Зафиксированное правило исходного GarmentCode; не скрытая мерка |
| `front_dart_fraction` | 0.6666666666666666 1 | Зафиксированное правило исходного GarmentCode; не скрытая мерка |
| `side_dart_depth_factor` | 0.75 1 | Зафиксированное правило исходного GarmentCode; не скрытая мерка |
| `dart_tip_factor` | 0.9 1 | Зафиксированное правило исходного GarmentCode; не скрытая мерка |

`expected_fit_error_mm=null`: ошибка посадки неизвестна. `expert_review.author=null`, `date=null`: проверки специалистом не было. Поля будущих property/golden/toile tests равны null, а не фиктивным именам успешно пройденных тестов. Контрольные примеры: [REFERENCE_CALCULATIONS.md](REFERENCE_CALCULATIONS.md).

Формулы кривых, длины дуги, замыкания вытачек, расклешения, горловины, обтачек и одношовного рукава должны получить собственные записи до реализации этих узлов. Не импортировать приложенные исследовательские `.py.txt` как готовый движок.
