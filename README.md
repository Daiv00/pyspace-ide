# PySpace Reminders

A tiny Flask + SQLite reminder web app designed as a simple deployment smoke test.

## Run
`pip install -r requirements.txt`
`python app.py`

## Render
Start command: `gunicorn app:app`
The SQLite database is stored in `reminders.db`. Use a persistent disk if you want data to survive container replacement.


## PySpace IDE
Это Flask-веб-приложение, а не консольная программа. Запуск `python app.py`
напрямую держит процесс открытым — это нормально для веб-сервера и не должно
считаться таймаутом.

Для режима проверки без запуска сервера:
`PYSPACE_RUNNER=1 python app.py`

Для обычного веб-запуска:
`python app.py`
или `gunicorn app:app`.
