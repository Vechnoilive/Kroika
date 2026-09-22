# Отчёт этапа 15 — системная валидация и выпуск

Дата: 2026-09-22. Версия приложения: `0.15.0`. Версия движка:
`kroika-geometry 0.8.1`.

## Требования и фактический результат

| Требование | Фактически |
| --- | --- |
| Аудит безопасности и приватности | Добавлены loopback-only публикация портов, security-заголовки, `no-store` для API, запрет прямого вызова выключенного провайдера, приватные права локальных файлов, безопасное перекодирование фото без EXIF/XMP и удаление проектов, профилей и фото. |
| Аудит производительности | Эталонное построение, SVG и PDF проверяются отдельными бюджетами 15/3/5 секунд. Это regression-бюджеты CI, а не SLA для любого компьютера. |
| Аудит доступности | Добавлена axe-проверка основного экрана без `serious/critical` нарушений, сохранены клавиатурный focus и текстовые статусы. |
| Аудит зависимостей | Python проверяется `pip check` и `pip-audit`, frontend — `npm audit`. Найденный уязвимый `pypdf 6.10.0` обновлён до `6.19.0`; после обновления известных уязвимостей не найдено. |
| Все автоматические проверки | Unit/integration/property/schema/SVG/PDF/UI/typecheck/build/security-аудиты проходят локально. Playwright запускается в GitHub Actions после установки Chromium; локальный runner не смог скачать браузер из-за ограничения среды. |
| Пилот с тётей | Не проведён. Шаблон журнала добавлен, но фиктивные проекты и подписи не создавались. |
| Документация, backup, migration, recovery | Добавлены проверяемый SQLite snapshot, фото, SHA-256-манифест, fail-closed восстановление, страховочная копия при замене и `PRAGMA user_version=1`. |
| Production только после `toile_verified` | Статус вычисляется из формул, эталона, инвариантов и независимых `paper/expert/toile` gates. Сейчас все десять изделий заблокированы. |

## Ошибки прошлых этапов, найденные аудитом

1. Стойка воротника рубашки строила контур, но не возвращала деталь: код возврата
   ошибочно находился после другой функции и был недостижим. Возврат и проверка
   контура восстановлены; версия движка повышена до `0.8.1`, чтобы не использовать
   старый кэш результата.
2. Выключенный Gemini можно было запросить прямым параметром API, обходя список
   разрешённых пользователю провайдеров. Реестр теперь отклоняет такой запрос.
3. Docker Compose публиковал backend/frontend на всех интерфейсах. Порты
   привязаны к `127.0.0.1`; сетевое развёртывание без аутентификации запрещено.
4. Не было полного пользовательского пути удаления локальных персональных
   данных и безопасного backup/recovery. Добавлены DELETE API и проверяемые CLI.
5. Исторические тесты этапов 12–14 жёстко считали старый каталог/скрипт последним
   и ломали следующую стадию. Проверки переведены на актуальный слой без
   ослабления продуктовых инвариантов.
6. Production-контейнер отделён от инструментов разработки: Ruff, Mypy, Bandit
   и `pip-audit` не включаются в runtime-образ.

## Основные файлы

- release gate и API: `pattern-engine/src/kroika_pattern_engine/garment_catalogue.py`,
  `backend/src/kroika_backend/app.py`;
- приватность и хранение: `repository.py`, `image_store.py`,
  `vision_providers.py`;
- backup/recovery: `backend/src/kroika_backend/backup.py`,
  `scripts/backup_local_data.py`, `scripts/restore_local_data.py`;
- аудит и CI: `requirements-stage15.txt`, `scripts/verify_stage15.py`,
  `.github/workflows/verify.yml`, `.github/workflows/full-regression.yml`;
- тесты: `tests/test_stage15_release.py`,
  `frontend/src/Stage15Accessibility.test.tsx`;
- эксплуатация: `SECURITY_PRIVACY.md`, `BACKUP_AND_RECOVERY.md`,
  `VALIDATION_AND_TOILE_LOG.md` и `references/stage15/pilot-log-template.json`.

## Точные проверки перед коммитом

| Команда | Результат |
| --- | --- |
| `.venv/bin/python -m pytest -q` | `157 passed`, `54 subtests passed` за `398.34s`; одно стороннее deprecation warning Starlette/AnyIO |
| `.venv/bin/python -m ruff check src backend/src pattern-engine/src scripts tests` | без ошибок |
| `.venv/bin/python -m mypy src backend/src pattern-engine/src scripts/backup_local_data.py scripts/restore_local_data.py` | `Success: no issues found in 42 source files` |
| `.venv/bin/python -m bandit -q -ll -r src backend/src pattern-engine/src` | без medium/high findings |
| `.venv/bin/python -m pip check` | `No broken requirements found` |
| `.venv/bin/python -m pip_audit -r requirements-runtime.txt --progress-spinner off` | `No known vulnerabilities found` |
| `npm test` | `12` файлов, `29` тестов прошли |
| `npm run typecheck` | прошёл |
| `npm run build` | прошёл; `24` модуля, основной JS `287.96 kB` (`87.43 kB` gzip) |
| `npm run audit:dependencies` | `found 0 vulnerabilities` |

`python scripts/verify_stage15.py` дополнительно запускает все mock Playwright E2E,
включая axe в настоящем Chromium, где доступна проверка цветового контраста.
В текущей локальной среде загрузка Chromium завершилась пустым архивом, поэтому
браузерная часть проверяется тем же скриптом в GitHub Actions с
`playwright install --with-deps chromium`. Это ограничение runner, а не
засчитанный успешный тест.

## Что проверил специалист

Закройщик и независимый security-аудитор в этом запуске не участвовали.
Автоматические эталоны не считаются их подписью. Реальных бумажных построений,
измерений печати, макетов и примерок нет.

## Ограничения и gate

- **AUTOMATED UNIT/STATIC/BUILD GATE: PASSED.**
- **LOCAL BROWSER GATE: BLOCKED окружением до результата CI.**
- **PILOT/PAPER/EXPERT/TOILE GATE: BLOCKED.**
- **PRODUCTION GATE: BLOCKED для всех десяти изделий.**

Приложение остаётся локальным исследовательским release candidate. SVG/PDF
можно использовать для бумажной проверки и макета, но не как подтверждённое
лекало для раскроя ткани.

## Запуск

```bash
python3 scripts/start_local.py
.venv/bin/python scripts/verify_stage15.py
```

На Windows: `py -3.12 scripts/start_local.py`, затем
`.venv\Scripts\python.exe scripts\verify_stage15.py`.

## Следующий шаг

Провести пилот с тётей на реальных проектах по шаблону журнала: сначала
проверить квадрат и длинную линию минимум на двух принтерах, затем бумажные
сопряжения, макет, посадку и свободу движения. Каждое изделие переводить в
production только после отдельных датированных `paper`, `expert` и `toile`
записей; не открывать статус общей галочкой.
