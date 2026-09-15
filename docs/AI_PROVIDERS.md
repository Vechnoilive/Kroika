# Контракт AI-провайдеров

Этап 10 реализует три взаимозаменяемых адаптера: `QwenProvider`, `GeminiProvider` и
полностью локальный `MockVisionProvider`. Pattern Engine от них не зависит и не получает
сырой ответ модели.

## Безопасная граница

Внешний провайдер получает только байты 1–4 изображений, допустимые категории и
словарь признаков. `request_id`, `project_id`, мерки, прибавки, припуски и координаты не
включаются в vendor payload. API-ключи читаются только backend из окружения и не
возвращаются в status API или браузер.

JPEG, PNG и WebP до 10 МБ проверяются по фактической сигнатуре, сохраняются локально
под случайным `img_*`, и только затем могут быть переданы выбранному сервису. Интерфейс
требует отдельное согласие именно для внешнего адаптера. Mock не читает и не отправляет
файл.

## Запрос и строгий ответ

Общий system prompt запрещает модели оценивать тело, размеры, скрытые детали,
припуски и геометрию. Для невидимого признака требуются `unknown`/`uncertain`,
пониженная уверенность, неопределённость и точный вопрос на русском.

Qwen вызывается через официальный OpenAI-compatible vision endpoint с multimodal
`image_url`. Gemini использует официальный `interactions` REST API с inline base64 и
`response_format` JSON Schema; для приватности запрос задаёт `store=false`. После любого
сервиса backend независимо выполняет:

1. JSON-разбор без `NaN`/`Infinity`, лишнего текста и ответов больше 256 КБ.
2. Проверку `ai-style-analysis.schema.json`, включая enum и запрет лишних полей.
3. Semantic validation против взаимоисключающих признаков и бездоказательного `ok`.

Официальные основания реализации: [Qwen VL OpenAI-compatible vision](https://www.alibabacloud.com/help/en/model-studio/qwen-vl-compatible-with-openai), [Gemini Interactions и retention](https://ai.google.dev/gemini-api/docs/interactions-overview), [Gemini image input](https://ai.google.dev/gemini-api/docs/image-understanding), [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output) и [доступные регионы Gemini](https://ai.google.dev/gemini-api/docs/available-regions). Региональные ограничения не обходятся; Qwen key и endpoint должны принадлежать одному региону.

## Отказы без ложного успеха

Таймаут, сетевой сбой, 429 и 5xx повторяются не более настроенного лимита (по умолчанию
два вызова всего). Авторизация, неверное изображение и невалидный ответ не повторяются.
HTTP API возвращает стабильные коды 422/429/503/504. UI сохраняет проект и изображение
и предлагает явный переход в demo/mock. Он никогда не выдаётся за анализ загруженного
фото.

## Настройка

Без ключей безопасный default — `KROIKA_AI_PROVIDER=mock`. Для внешнего сервиса задайте
только на backend:

```dotenv
KROIKA_AI_PROVIDER=qwen
QWEN_API_KEY=...
QWEN_BASE_URL=https://WORKSPACE.REGION.maas.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3-vl-plus
```

или `KROIKA_AI_PROVIDER=gemini`, `GEMINI_API_KEY` и при необходимости
`GEMINI_MODEL`. Сервер запускается и при неполной внешней конфигурации, чтобы mock и
ручной сценарий не были заблокированы.

## Evaluation и выбор default

`evaluation/stage10` содержит 50 собственных CC0 синтетических схем с seed-разметкой.
`scripts/evaluate_stage10.py` одинаково считает для Qwen/Gemini schema/semantic validity,
точность каждого признака, полноту вопросов, Brier score уверенности, latency и cost.

Синтетика проверяет интеграцию, но не качество на реальной одежде. Переключение default
на внешний сервис остаётся заблокированным до одинакового A/B минимум на 50 разрешённых
реальных изображениях со статусом `expert_verified`. До этого `mock` — безопасный
операционный default, а Qwen/Gemini доступны как явно выбранные адаптеры.
