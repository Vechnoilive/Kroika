# Резервное копирование и восстановление

Резервная копия содержит согласованный SQLite snapshot, локальные фото и
`manifest.json` с размером и SHA-256 каждого файла. Перед восстановлением
проверяются состав, пути, контрольные суммы, `PRAGMA integrity_check` и версия
схемы. Неизвестная более новая схема открываться не будет.

## Создать копию

Остановите Kroika либо убедитесь, что в этот момент никто не сохраняет проект:

```bash
.venv/bin/python scripts/backup_local_data.py backups/kroika-2026-09-22
```

В PowerShell замените `.venv/bin/python` на `.venv\Scripts\python.exe`.
Каталог назначения должен быть новым — существующая копия не перезаписывается.
Храните копию на зашифрованном диске: она содержит мерки и фотографии.

## Проверить восстановление в пустой каталог

```bash
.venv/bin/python scripts/restore_local_data.py backups/kroika-2026-09-22 \
  --database recovery-test/kroika.db --images recovery-test/images
```

Запустите приложение с `KROIKA_DATABASE_PATH` и
`KROIKA_IMAGE_STORAGE_PATH`, указывающими на тестовый каталог, и откройте
несколько проектов.

## Заменить рабочие данные

Сначала остановите приложение. Режим замены требует отдельный новый каталог
страховочной копии и не запускается без него:

```bash
.venv/bin/python scripts/restore_local_data.py backups/kroika-2026-09-22 \
  --replace --safety-backup backups/pre-restore-2026-09-22
```

После восстановления запустите `python scripts/verify_stage15.py`. Если
версия схемы резервной базы новее приложения, установите совместимую версию
Kroika; понижать `user_version` вручную запрещено.
