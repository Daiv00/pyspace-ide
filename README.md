# PySpace IDE v1.3

Онлайн многопользовательская IDE: Python, HTML, CSS, SQL, загрузка/скачивание файлов, проекты и общий доступ между пользователями.

## Render
Dockerfile уже настроен на Gunicorn и порт `8080`.

Переменные:
- `PYSPACE_SECRET` — секрет сессий
- `PYSPACE_ADMIN_USER` — начальный admin
- `PYSPACE_ADMIN_PASSWORD` — пароль начального admin

## Важно про хранение
Файлы хранятся на сервере в `storage/`, поэтому отключение телефона/браузера/локального LAN не удаляет их. Для гарантированного сохранения между пересозданиями Render в следующем этапе рекомендуется подключить persistent storage/object storage + PostgreSQL.


## v1.5
Reliable Admin/Exchange controls and an interactive input() dialog.


## v1.7
Fixed the modal null-reference that broke Admin and Exchange dialogs; admin role is refreshed from the server before opening the panel.


## v1.8
- One-click QR room for sending files/text to PySpace.
- Redesigned dashboard/workspace interface for future tools.
- QR link and PNG download.


## v1.9
- Fixed QR generator: quickQR is now async.
- Short share links use `/s/XXXXXXX` with 7-character base62 tokens.
- Added short redirect route for easier manual entry.
- Refreshed the main UI with a cleaner product/workspace layout.

## v2.0
- Fixed JavaScript syntax error that prevented login/register buttons from being wired.
- Fixed Monaco CDN URL.
- Added `string` import required by short QR token generation.
- Initializes `local_hub` on startup.
- Project files are written directly to `storage/project_<id>/` and share files to `local_hub/share_<token>/`, so they remain after a normal process restart.
- Added `/api/my-shares` for persistent share history.
- Added share manifest files.
- On Render, persistent files across redeploys/restarts require a Render Persistent Disk mounted to the application data directory; otherwise Render's filesystem is ephemeral.
