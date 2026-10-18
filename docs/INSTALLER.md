# Windows-установщик · 0.9.2

Исходник: installer/Orbita.iss. Компилятор: Inno Setup 7.1.0 x64.
Собственный AppId: `Technomedved.Orbita.Desktop` (сохранять при обновлениях).
`PrivilegesRequired=lowest`, без override на ALLUSERS, HKCU uninstall record,
`%LOCALAPPDATA%\Programs\Orbita`, стандартный профиль данных вне программы.
Минимальная Windows — 11 (build 22000); x64-compatible, ARM64 не проверен.

## Сборка

Положите ISCC.exe в `.build-tools/inno` либо задайте `ORBITA_ISCC`.
Используйте официальный подписанный компилятор; зависимости самого компилятора
не добавляются в исходники или пакет приложения. Исходный загрузчик 7.1.0:
https://github.com/jrsoftware/issrc/releases/tag/is-7_1_0 .
SHA-256 innosetup-7.1.0-x64.exe:
`0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f`.
Проверенная подпись загрузчика — Pyrsys B.V. Лицензия: licenses/InnoSetup.
Компилятор можно установить в переносимом режиме `/PORTABLE=1 /CURRENTUSER`.

1. Сохранить исходники коммитом; собрать desktop через build_desktop.py.
2. `python build_installer.py` — проверяет версию, commit и отсутствие dirty-сборки.
3. `python verify_installer_release.py` — реальные изолированные установки.
4. `python release_artifacts.py` — ZIP и SHA256SUMS, включая setup при наличии.

Production installer привязывается к manifest бинарного пакета. Установщик
не подписан; подпись загрузчика компилятора не подписывает созданный setup.
Автообновление не реализовано.

## Защита данных

- AppMutex включает общий `Local\Orbita.Desktop.InstallGuard` нового GUI
  и прежние mutex стандартных профилей. Текст просит «трей → Выход».
- Только marker `orbita-installation.ini` с точным ProductId разрешает
  чистку собственных `_internal/docs/licenses/training` перед обновлением.
  Непустая чужая папка и junction на этих каталогах отклоняются.
- Installer не открывает SQLite, не включает автозапуск, не удаляет portable-копию.
- Uninstall по умолчанию сохраняет выбранный стандартный профиль. В GUI —
  явный Yes/No/Cancel с default No; в silent production очистки данных нет.
- Очистка проверяет точное совпадение со стандартным показанным путём.
  Inno DelTree удаляет reparse point, не проходит по его цели.
- Запись Run удаляется только при точном совпадении команды с установленной
  Orbita.exe --background. Чужие portable-команды остаются.

## Проверки

verify_installer_release.py компилирует отдельные test installers с уникальными
AppId, именем Run и жёстко заданным профилем внутри data/installer-tests.
Только этот вариант поддерживает PURGETESTDATA; production его не обрабатывает.
Настоящие профили/Run Орбиты не перенаправляются и не удаляются.

Проверяются настоящий payload 0.9.1 → новый, блокировка работающего процесса,
неизменность SQLite, очистка старой DLL, сохранение неизвестного пользовательского
файла, HKCU без HKLM, удаление/повторная установка, политика автозапуска и
junction с внешним маркером. Проверка выполняется не под администратором.
Отчёт: data/installer-release-verification.json.

Это один Windows 11 аккаунт с отдельным compiled test AppId, не парк компьютеров.
Silent-проверка не нажимает реальный GUI Yes/No/Cancel. Отдельно проверяйте
визуал мастера и диалога перед массовой поставкой. Сценарии не требуют прав
администратора; политики сторонней организации могут запретить установку.
