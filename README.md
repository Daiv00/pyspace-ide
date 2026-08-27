# PySpace IDE 5.0

Онлайн-среда разработки в браузере: проекты, папки, вкладки файлов, редактор Monaco,
запуск кода без белых списков команд, настоящий терминал (PTY), живой предпросмотр
веб-проектов и обмен файлами по QR-коду.

Написана с нуля на Flask, разложена по модулям, деплоится на Render одной командой
`git push`.

---

## Что умеет

| Возможность | Описание |
|---|---|
| Проекты | Сколько угодно проектов у пользователя, у каждого своя папка на диске |
| Файлы и папки | Дерево с любой вложенностью, создание/переименование/удаление, drag-and-drop загрузка |
| Вкладки | Несколько открытых файлов, индикатор несохранённых правок, `Ctrl+S` / `Ctrl+Shift+S` |
| Редактор | Monaco (движок VS Code): подсветка, автоотступы, поиск, миникарта |
| Запуск кода | Python в реальной папке проекта, ввод через STDIN, код выхода и время работы |
| Без ограничений | Нет белых списков: любой код, любые файлы, любые команды в терминале |
| Терминал | Полноценный PTY-bash через WebSocket (xterm.js), `git`, `pip`, `python`, всё остальное |
| Пакеты | `pip install` в папку `.packages` внутри проекта, список установленного |
| Предпросмотр | HTML/CSS/JS проекта открывается рядом с кодом в песочнице (`sandbox` CSP) |
| Поиск | Поиск по имени файла и по содержимому в рамках проекта |
| Обмен по QR | Комната передачи файлов: открыл QR-код телефоном и загрузил файлы без входа |
| ZIP | Скачать проект или папку архивом, импортировать проект из ZIP |
| Хранилище | Личное «хранилище» файлов пользователя вне проектов |
| Админка | Пользователи, роли, лимиты, статистика — для роли `admin` |
| Тема | Тёмная и светлая, палитра команд `Ctrl+K`, изменяемые размеры панелей |

Все надписи, комментарии в коде и документация — на русском.

---

## Быстрый старт локально

Linux / macOS:

```bash
./run_local.sh
```

Windows:

```bat
run_local.bat
```

Скрипт создаст виртуальное окружение, установит зависимости и поднимет сервер на
<http://127.0.0.1:8000>. Первый зарегистрированный пользователь автоматически
становится администратором (если не заданы `PYSPACE_ADMIN_USER` / `PYSPACE_ADMIN_PASSWORD`).

Вручную:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export PYSPACE_ENV=development PYSPACE_SECRET=dev-secret
python -m flask --app wsgi:app run --port 8000
```

Проверка работоспособности:

```bash
python tests/test_smoke.py          # полный путь пользователя по API
python tests/ws_check.py            # PTY-терминал по WebSocket (сервер должен быть запущен на :8099)
```

---

## Структура

```
pyspace-ide/
├─ wsgi.py                 точка входа (gunicorn/flask), gevent-патч для WebSocket
├─ Dockerfile              образ для Render (python:3.12-slim + bash, git, curl)
├─ render.yaml             Blueprint Render: сервис, переменные, автодеплой
├─ requirements.txt
├─ run_local.sh / .bat     локальный запуск одной командой
├─ app/
│  ├─ __init__.py          create_app: конфиг, БД, роуты, заголовки безопасности
│  ├─ config.py            все переменные окружения в одном объекте settings
│  ├─ db.py                SQLite + миграции схемы
│  ├─ repo.py              работа с таблицами (users, projects, shares, drops…)
│  ├─ auth.py              сессии, роли, доступ к проекту
│  ├─ paths.py             безопасные пути (защита от выхода за корень проекта)
│  ├─ fs_tree.py           дерево файлов, поиск, чтение/запись
│  ├─ archives.py          ZIP: экспорт и импорт
│  ├─ runner.py            запуск Python и pip с таймаутами и лимитами вывода
│  ├─ shell.py             PTY-сессия (bash) для терминала
│  ├─ qrcodes.py           генерация QR для комнат обмена
│  ├─ sockets.py           WebSocket-канал /ws/terminal/<project_id>
│  ├─ api/                 REST: auth, projects, files, run, drops, admin
│  ├─ views/               страницы: IDE, комната обмена, предпросмотр, /healthz
│  ├─ templates/           base, ide, drop, error
│  └─ static/
│     ├─ css/              tokens, base, components, shell, drop
│     └─ js/
│        ├─ core/          dom, api, store, toast, modal, palette, split
│        ├─ features/      editor, tabs, tree, projects, runner, dock, terminal,
│        │                 preview, search, packages, drops, vault, admin, auth
│        └─ main.js        сборка приложения, горячие клавиши, палитра команд
└─ tests/                  smoke-тест API и проверка терминала
```

---

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `PORT` | `8080` | порт (Render задаёт сам) |
| `PYSPACE_ENV` | `production` | `development` включает подробные ошибки и сброс кэша статики |
| `PYSPACE_SECRET` | случайный | ключ подписи cookie-сессии |
| `PYSPACE_SESSION_DAYS` | `30` | срок жизни сессии |
| `PYSPACE_DATA_DIR` | `/data` или `./var` | корень данных (БД, проекты, комнаты обмена) |
| `PYSPACE_DB` | `<data>/pyspace.db` | путь к базе |
| `PYSPACE_STORAGE_DIR` | `<data>/projects` | папки проектов |
| `PYSPACE_DROPS_DIR` | `<data>/drops` | файлы комнат обмена |
| `PYSPACE_MAX_UPLOAD_MB` | `200` | максимум на загрузку |
| `PYSPACE_MAX_FILE_KB` | `4096` | максимум на открытие файла в редакторе |
| `PYSPACE_RUN_TIMEOUT` | `20` | таймаут запуска кода, с |
| `PYSPACE_PIP_TIMEOUT` | `180` | таймаут pip, с |
| `PYSPACE_OUTPUT_LIMIT` | `200000` | лимит символов вывода |
| `PYSPACE_STDIN_LIMIT` | `65536` | лимит STDIN |
| `PYSPACE_ENABLE_PTY` | `1` | терминал |
| `PYSPACE_ENABLE_PREVIEW` | `1` | живой предпросмотр |
| `PYSPACE_ENABLE_REGISTRATION` | `1` | открытая регистрация |
| `PYSPACE_SHELL` | `/bin/bash` | оболочка терминала |
| `PYSPACE_ADMIN_USER` / `PYSPACE_ADMIN_PASSWORD` | — | создать/повысить администратора при старте |
| `PYSPACE_GEVENT` | `0` | `1` — включить gevent-патч (нужно для WebSocket под gunicorn) |

---

## Деплой на Render

Пошаговая инструкция — в [DEPLOY.md](DEPLOY.md). Коротко: закинуть папку в репозиторий
GitHub → в Render создать **Blueprint** из этого репозитория → задать логин и пароль
администратора → дальше каждый `git push` в `main` деплоит сам.

⚠️ На плане Free диск не подключается: файлы проектов и база живут только до
следующего деплоя или перезапуска. Как включить постоянный диск — в DEPLOY.md.

---

## Безопасность

- Все пути проходят через `app/paths.py`: выход за корень проекта (`../`) отклоняется.
- Предпросмотр отдаётся с `Content-Security-Policy: sandbox …` — чужой код не имеет
  доступа к cookie IDE.
- Пароли хранятся хэшами Werkzeug (`pbkdf2`).
- Комнаты обмена работают по одноразовому токену и живут ограниченное время.
- Запуск кода и терминал не имеют белых списков — это осознанное требование к проекту.
  Не открывайте регистрацию (`PYSPACE_ENABLE_REGISTRATION=0`) для незнакомых людей:
  любой пользователь получает shell внутри контейнера.
