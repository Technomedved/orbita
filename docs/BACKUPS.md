# Резервирование и восстановление профиля

Модули: `backup_service.py` (формат/проверка/снимок/retention/restore),
`profile_access.py` (межпроцессная SQLite-gate), `profile_recovery.py`
(durable journal и копирование), `health_service.py` (read model и allowlist
диагностики), `data_ui.py` (Qt-адаптер и фоновые операции).
Пользовательское руководство: [BACKUPS.md](../release_docs/BACKUPS.md).

## Формат 1 / схема 9

ZIP содержит ровно `manifest.json` (до 64 KiB) и `inbox.sqlite` (до 512 MiB).
Manifest: product=orbita-profile, format, app_version, schema, created с offset,
automatic, owner, profile_id, counts, excluded, files с bytes/SHA256. Дубликаты имён,
другие пути, symlink и шифрованные entries отклоняются. Распаковка потоковая
с реальным лимитом, не только проверкой заголовка. База проверяется через
integrity_check, whitelist таблиц, revision triggers и модель расписаний.
Старые `.sqlite` migration backups и будущие несовместимые схемы не принимаются.

SQLite snapshot создаётся через [Online Backup API](https://www.sqlite.org/backup.html).
Файлового копирования открытой основной базы нет. Архив пишется во временный
файл рядом с назначением, проверяется распаковкой, синхронизируется и
переименовывается. Успех фиксируется после проверки. `backup_state` хранит
последнюю попытку и прежний last_success отдельно.

## Процессы, recovery и настройки

`.profile-access.sqlite` — отдельная gate-база. Нормальный store.connect и
initialize держат shared read transaction; restore держит EXCLUSIVE.
Thread-local reentrancy не создаёт вложенных gate-транзакций. ОС освобождает
SQLite-lock после смерти процесса. Gate — технический адаптер стандартной
библиотеки, без Qt/Win32. Постоянный RevisionReader берёт gate на чтение;
перед restore GUI закрывает его, останавливает engine и ожидает workers.
Старые бинарники до 0.9.3 gate не знают и должны быть закрыты.

Под EXCLUSIVE создаётся страховочный архив и `.restore/previous.sqlite`,
затем подготовленная incoming.sqlite. Журнал содержит только format/phase:
prepared → applying → committed; записи через fsync + replace. Incoming
копируется Backup API в существующий файл базы, с транзакционным commit,
без файловой подмены открытого inode/handle. При незавершённом journal любой
следующий store-access сначала восстанавливает previous. Committed требует
только очистки собственных фиксированных файлов. Неизвестный журнал приводит
к отказу доступа, а не попытке угадать содержимое. Проверена смерть процесса;
физическое отключение питания/неисправность накопителя не моделировались.

Схема 8 → 9 добавляет стабильный переносимый profile_uuid в settings,
publication_receipts для dedupe-публикаций и выключенный
шаблон profile-backup. До миграции обычный проверенный SQLite backup.
Restore сохраняет terminal receipts актуального устройства для существующих
task IDs, ключи публикаций и done-состояния совпавших напоминаний только при
совпадении profile_uuid. Независимые профили не наследуют чужие done/dedupe
из-за совпавших числовых run IDs. История
копии остаётся, delivered помечается, чтобы не повторять старые toasts.
Общая пауза по умолчанию true, enabled обычных задач/их timezone не меняются.
Автокопии отключаются, folder очищается, sensor refresh выключается;
window_geometry/topmost/backup_state берутся с текущего устройства. Реестр
автозапуска не читается и не записывается при restore.

`.backup-device.json` и `.auto-backups.json` — локальные служебные файлы,
не экспортируются. Retention удаляет только зарегистрированные файлы в
текущей папке с совпавшими hash/owner/automatic; manual/изменённые/чужие
не затрагиваются. Последняя исправная копия сохраняется до проверки новой.

## Проверки и продолжение

`test_backup.py`: snapshot при записи, полнота, corruption/limits, safety failure,
crash/recovery, cross-process publisher, receipts, quiet/scheduled backup,
retention, migration, diagnostic privacy. `test_data_ui.py`: drafts,
background handshake, route, restore/restart, failure resume и busy close.
`run_checks.py` включает оба набора. Фактические результаты — data/checks-desktop.json.
Отдельные Windows проверки сборки/установщика фиксируются перед выпуском.
