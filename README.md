# Kroika

Русскоязычное веб-приложение для закройщика: ручные женские мерки + подтверждённое описание фасона → детерминированная векторная выкройка в миллиметрах → SVG и A4 PDF 1:1.

**Завершён этап 3 из 15: архитектура и проверяемые контракты данных. Веб-приложение будет собрано на этапе 4.**

Пользователь поручил выбрать рабочие ответы вместо интервью. Они оформлены как решения разработчика, без фиктивного согласования тётей. Для исследовательского прототипа выбран `kroika-gc-woven 0.1.0` на основе зафиксированного открытого GarmentCode; статус `experimental`.

## Что сделано

- Перенесены требования, сценарий, словарь и дорожная карта этапа 1.
- Сопоставлены подходы и определён источник вычислительных блоков с точной версией и MIT-уведомлением.
- Записаны 41 скалярная формула, единицы, коэффициенты и 3 синтетических профиля с 123 контрольными значениями.
- Подготовлены пробные прибавки/припуски, критерии точности и проверка расчётов без внешних зависимостей.
- Выполнен отдельный запуск 12 исходных геометрических заготовок; измерены реальные длины интерфейсов и записаны несогласованные соединения.
- Определены семь основных сущностей проекта, 13 JSON Schema 2020-12, OpenAPI 3.1 и девять будущих API-операций.
- Добавлены независимые интерфейсы AI/Pattern Engine, стабильный hash входов, смысловые проверки и безопасный реестр миграций.

Это не готовые лекала. Полная геометрическая спецификация первого блока, одношовный рукав, независимые полные ручные построения и экспертная проверка ещё отсутствуют. **Исходный gate этапа 2: BLOCKED.** Успешные численные тесты не означают проверенную посадку.

## Проверить этапы 2–3

Арифметика этапа 2 использует только стандартную библиотеку Python 3.12+:

```bash
python3 scripts/verify_stage2.py
```

Windows:

```powershell
py -3.12 scripts/verify_stage2.py
```

Контрактные тесты этапа 3 требуют небольшого отдельного окружения. Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-stage3.txt
python scripts/verify_all.py
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-stage3.txt
python scripts/verify_all.py
```

Ожидаемый результат: 15 тестов этапа 2 и 25 тестов этапа 3, `OK`. API-ключи и Docker не нужны. Проверки не создают выкройки и не переписывают эталоны.

## Документы

| Файл | Для чего |
| --- | --- |
| [PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) | Требования и границы MVP |
| [PATTERNMAKER_INTERVIEW.md](docs/PATTERNMAKER_INTERVIEW.md) | Рабочие ответы на все 20 вопросов |
| [METHOD_RESEARCH.md](docs/METHOD_RESEARCH.md) | Источники, сравнение и причины выбора |
| [PATTERN_METHOD.md](docs/PATTERN_METHOD.md) | Методика, определения мерок и незакрытые части |
| [FORMULA_REGISTRY.md](docs/FORMULA_REGISTRY.md) | 41 формула и метаданные |
| [REFERENCE_CALCULATIONS.md](docs/REFERENCE_CALCULATIONS.md) | Три пошаговых вычислительных листа |
| [UPSTREAM_BLOCK_AUDIT.md](docs/UPSTREAM_BLOCK_AUDIT.md) | Фактический запуск исходных заготовок и измеренные швы |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Модули, границы данных, hash и API |
| [AI_PROVIDERS.md](docs/AI_PROVIDERS.md) | Единый интерфейс и безопасная граница AI |
| [PROJECT_MIGRATIONS.md](docs/PROJECT_MIGRATIONS.md) | Политика версий и миграций проектов |
| [FIT_AND_TOLERANCES.md](docs/FIT_AND_TOLERANCES.md) | Прибавки, припуски и допуски |
| [VALIDATION_AND_TOILE_LOG.md](docs/VALIDATION_AND_TOILE_LOG.md) | Статус специалиста, бумаги и макетов |
| [ROADMAP.md](docs/ROADMAP.md) | Все 15 этапов |
| [STAGE_02_REPORT.md](docs/STAGE_02_REPORT.md) | Исследование методики и его ограничения |
| [STAGE_03_REPORT.md](docs/STAGE_03_REPORT.md) | Проверки и gate архитектурного этапа |

Qwen/Gemini будут анализировать фасон; мерки тела и координаты лекал не поручаются нейросети. Контракты готовы, а реальные API-обработчики и провайдеры относятся к следующим этапам.

Контракты: [PatternProject](schemas/v1/pattern-project.schema.json), [OpenAPI](schemas/openapi.v1.yaml), [пример проекта](examples/v1/example-dress-project.json). Источники и лицензия: [THIRD_PARTY_NOTICES.md](LICENSES/THIRD_PARTY_NOTICES.md). Следующий этап — каркас веб-приложения и локальный запуск.
