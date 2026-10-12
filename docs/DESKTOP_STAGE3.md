# Самостоятельное приложение Windows

## Установка и работа

Скачайте `Kroika-0.3.0-windows-x64-setup.exe` из [выпусков](https://github.com/Vechnoilive/Kroika/releases), запустите и откройте **Кройку** из меню «Пуск». Python, Node.js, терминал и исходники для запуска не нужны. Поддерживаются Windows 10 1809+ и Windows 11 x64. ARM64 с эмуляцией x64 отдельно не проверен.

Установка выполняется для текущего пользователя в `%LOCALAPPDATA%\Programs\Kroika`; ярлык на рабочем столе доступен как опция. Интерфейс, схемы, движок, Python, библиотеки окна и экспорта входят в программу. Полный offline-установщик WebView2 x64 с проверенной подписью Microsoft включён в setup и запускается только при отсутствии runtime. Для Gemini нужны интернет и собственный ключ — настройте их в **«Настройках приложения»**.

`portable.zip` распакуйте целиком и запустите `Kroika.exe`; WebView2 уже должен быть установлен. Данные portable-версии также находятся в постоянной пользовательской папке. Перенос из веба и переменные окружения: [второй этап](DESKTOP_STAGE2.md).

## Обновление и сохранность

В настройках отображается версия. **«Проверить обновления»** обращается только к публичному API GitHub без API-ключей, мерок, проектов и фотографий. Новая версия доступна при наличии setup и контрольных сумм. Проверка выполняется по нажатию. Сохраните проект, закройте окно и запустите новый установщик со страницы выпусков; автоматического запуска скачанного кода нет.

Постоянный AppId сохраняет папку установки. Перед копированием нового runtime удаляются старые файлы `_internal`, чтобы не смешивать Python/DLL разных версий. Windows mutex блокирует установку и удаление при открытом приложении; процессы не завершаются принудительно.

Проекты, SQLite/WAL, фотографии, настройки, Credential Manager и профиль окна остаются в `%LOCALAPPDATA%\Kroika`. Setup/uninstall не удаляют эту папку. При первом запуске другой версии база и фотографии копируются через SQLite backup API в `backups/before-desktop-…`; проверяются целостность и контрольные суммы. Ошибка копирования останавливает запуск до изменения маркера версии. Ключ не включается в резервные копии.

Установленная программа не импортирует автоматически папки рядом с exe; для прежних данных есть диалог импорта. Откат программы выполняется установкой старого выпуска после закрытия окна. Восстановление базы после несовместимой миграции выполняется отдельно; установщик не понижает версию схемы.

## Сборка

Собирайте на Windows x64 с Python 3.12, Node.js 24 и Inno Setup 6. Эти инструменты нужны только разработчику:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-desktop-build.txt
.venv\Scripts\python.exe -m pip install --no-deps -e . -e pattern-engine -e backend
$runtime = Join-Path $env:TEMP "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
Invoke-WebRequest "https://go.microsoft.com/fwlink/?linkid=2124701" -OutFile $runtime
.venv\Scripts\python.exe scripts/build_desktop.py --webview2-installer $runtime
```

Скрипт проверяет подпись WebView2, собирает production-интерфейс, создаёт собственный значок и ресурс версии, затем PyInstaller onedir, setup, portable.zip и `SHA256SUMS.txt` в `dist/desktop`. Сведения о зависимостях и доступные лицензии включаются в `kroika_resources/THIRD_PARTY`, прежние уведомления — в `LICENSES`.

В bundle явно включены JSON-схемы, реестр модулей, изображения мерок, pywebview DLL/JS, Python.NET, Windows keyring и Uvicorn-протоколы. `freeze_support` вызывается до импорта приложения. Ресурсы читаются из `_MEIPASS/kroika_resources` независимо от текущей папки. Диагностические примеры синтетические; пользовательских данных в сборке нет. Веб и исходный `scripts/start_desktop.py` продолжают работать.

## Проверки и публикация

Workflow **Kroika Windows installer** проверяет API и весь интерфейс, собирает setup и устанавливает его в путь с пробелами, кириллицей и `#`. Затем Python, py и Node исключаются из PATH, PYTHONPATH очищается; запускаются установленный exe и настоящее окно WebView2. Проверяются построение, PDF/SVG/JSON, фотографии, профили, повторное открытие данных, React/native bridge, переустановка, очистка старого runtime и сохранность после uninstall. Runner содержит средства разработки вне PATH; это не отдельная чистая физическая машина.

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_desktop.py tests/test_desktop_stage2.py tests/test_desktop_stage3.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_desktop_install.ps1
```

`--self-test RESULT_JSON` проверяет ресурсы и настоящий сервер во временном хранилище; `--smoke-test RESULT_JSON` открывает настоящее окно с текущим изолированным профилем, проверяет React/bridge и закрывает его. Обычный запуск не выполняет диагностику. CI сохраняет отчёты и архив **Kroika-windows-x64**. После успешных установочных проверок на main новая версия публикуется как `desktop-vVERSION`; существующий выпуск не перезаписывается. Для следующего выпуска увеличьте `desktop_version.VERSION` и обновите release notes.

Собственного сертификата подписи издателя нет. Setup/Kroika.exe не подписаны Authenticode; возможен SmartScreen. SHA256 не заменяет подпись издателя. WebView2 проверяется по действительной подписи Microsoft. Автоматический запуск обновлений, сертификат издателя и установщики macOS/Linux в эту сборку не входят.
