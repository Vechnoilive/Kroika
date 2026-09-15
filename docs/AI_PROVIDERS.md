# Контракт AI-провайдеров

Архитектура содержит три взаимозаменяемых адаптера: `QwenProvider`, `GeminiProvider` и
полностью локальный `MockVisionProvider`. На этапе 11 в пользовательском интерфейсе
включены только Qwen и mock. Gemini сохранён выключенным для возможного будущего решения.
Pattern Engine от провайдеров не зависит и не получает сырой ответ модели.

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

Список вариантов интерфейса задаёт `KROIKA_ENABLED_AI_PROVIDERS=mock,qwen`. Gemini можно
будет включить только явным изменением этого списка; сейчас продукт его не подключает,
VPN и другие способы обхода региональных ограничений не используются. Сервер запускается
и при неполной внешней конфигурации, чтобы mock-сценарий не был заблокирован.

## Evaluation и выбор default

`evaluation/stage10` содержит 50 собственных CC0 синтетических схем с seed-разметкой.
`scripts/evaluate_stage10.py` одинаково считает для Qwen/Gemini schema/semantic validity,
точность каждого признака, полноту вопросов, Brier score уверенности, latency и cost.

Синтетика проверяет интеграцию, но не качество на реальной одежде. Переключение default
на автоматический внешний default остаётся заблокированным до проверки минимум на 50
разрешённых реальных изображениях со статусом `expert_verified`. По продуктовому решению
Qwen уже является единственным внешним вариантом, но без ключа `mock` остаётся безопасным
операционным default. Это решение о доступности, а не заявление о доказанном качестве.
