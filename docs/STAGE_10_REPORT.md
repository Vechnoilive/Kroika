# Отчёт этапа 10 — анализ изображений

## Реализовано

- Единый provider registry с `QwenProvider`, `GeminiProvider`, `MockVisionProvider` и
  выбором через окружение либо один запрос.
- Реальная передача JPEG/PNG/WebP согласно официальным форматам Qwen/Gemini; endpoint,
  region и model не зашиты в код.
- Общий ограничивающий prompt, provider JSON Schema, строгий локальный JSON/schema/
  semantic validation, таймаут и максимум два вызова.
- Локальное безопасное хранилище изображений и status API без ключей.
- Последовательный экран выбора: недоступные сервисы объяснены, внешняя отправка требует
  согласия, при сбое доступен явный demo/mock.
- 50 собственных синтетических PNG с seed-разметкой и единый A/B-оценщик.

Backend и frontend имеют версию `0.10.0`. Контракты геометрии не менялись.

## Проверка текущего этапа

`python scripts/verify_stage10.py` запускает только новые проверки этапа 10:

- backend unit/contract/security/evaluation tests;
- `VisionAnalyzer.test.tsx`;
- production-сборку frontend;
- HTTP smoke provider discovery → upload → недоступный Qwen → явный mock fallback.

Старые stage-тесты и `verify_all.py` этой командой не запускаются. Реальные платные API
в CI не вызываются; wire format проверяется через детерминированный transport.

## Gate

Автоматический gate интеграции закрывается тестами. Приложение сохраняет рабочий mock
при недоступности любого API. Однако продуктовый выбор Qwen против Gemini **AWAITING
EXPERT A/B**: нужны минимум 50 разрешённых фотографий реальной одежды, независимая
разметка закройщика и прогоны обоих сервисов. До этого default остаётся `mock`, а
синтетический набор нельзя выдавать за доказательство качества распознавания.
