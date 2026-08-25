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
