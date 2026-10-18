# Сторонние компоненты Орбиты 0.9.2

Собственный код проекта: MIT, см. LICENSE. Эта лицензия не заменяет условия
зависимостей. Полные тексты и исходные уведомления находятся в `licenses/`.

| Компонент | Условия и расположение |
|---|---|
| Python 3.12.14 | PSF и включённые уведомления: licenses/Python/LICENSE.txt |
| Qt / PySide6 / Shiboken 6.12.0 | Динамические LGPLv3-библиотеки; тексты LGPLv3/GPLv3 и сторонние уведомления: licenses/qtbase, licenses/pyside-setup и каталоги модулей |
| Qt SVG, Image Formats, Positioning, Serial Port, Declarative | Уведомления соответствующих модулей в licenses; Declarative включён из-за транзитивных Qt-библиотек |
| OpenSSL 3.6.4 | Apache 2.0: licenses/OpenSSL/LICENSE.txt |
| libffi | MIT: licenses/libffi/LICENSE.txt |
| tzdata 2026.5 / IANA | Apache 2.0 и условия данных: licenses/tzdata |
| SQLite | Public domain: https://www.sqlite.org/copyright.html |
| PyInstaller 6.22.3 | GPL с исключением bootloader: licenses/PyInstaller/LICENSE.txt; исключение позволяет распространять собственный код под MIT |
| Inno Setup 7.1.0 | Сборка установщика: licenses/InnoSetup/LICENSE.txt; собственная лицензия Inno, не MIT |
| Microsoft runtime | DLL Windows/VC runtime из среды Python; права Microsoft сохраняются. См. https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files |

## Исходники библиотек и замена

Полные неизменённые архивы Qt/PySide соответствующих версий предоставляются
отдельным архивом `Orbita-0.9.2-library-sources.zip` рядом с Windows-архивом.
Их адреса и проверенные SHA-256: licenses/sources.json. Не распространяйте
Windows-архив отдельно от доступных библиотечных исходников.

Библиотеки связаны динамически и доступны в `_internal`. Инструкция замены,
сборки и права пользователя: licenses/README.md. Код Qt не менялся.
Virtual Keyboard и неиспользуемый PDF-плагин исключены из поставки.
Инвентаризация файлов с SHA-256 находится внутри Windows ZIP в bundle-inventory.json.

## Данные и сервисы

Погода и поиск: [Open-Meteo](https://open-meteo.com/),
данные [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Орбита преобразует данные в прогноз по выбранным часам. Бесплатный API
предназначен для некоммерческого использования и ограничивает запросы:
https://open-meteo.com/en/terms . Эти условия независимы от MIT собственного кода.

Учебные таблицы вымышленные. Материалы ссылаются на документацию IBM;
проект не включает Db2 и не является продуктом IBM.

Это технический перечень поставки и текстов лицензий, а не юридическое
заключение о любом будущем способе монетизации или распространения.
