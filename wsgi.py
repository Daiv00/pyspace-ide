"""Точка входа для gunicorn и локального запуска.

Gunicorn: gunicorn -k gevent -w 1 wsgi:app
Локально:  python wsgi.py
"""

from __future__ import annotations

import os

# gevent должен пропатчить стандартную библиотеку раньше всех импортов,
# иначе WebSocket-терминал будет блокировать воркер.
if os.getenv("PYSPACE_GEVENT", "1") == "1":
    try:
        from gevent import monkey

        monkey.patch_all()
    except ImportError:  # локальная разработка без gevent
        pass

from app import create_app  # noqa: E402
from app.config import settings  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(
        host=settings.host,
        port=settings.port,
        debug=settings.is_dev,
        threaded=True,
        use_reloader=settings.is_dev,
    )
