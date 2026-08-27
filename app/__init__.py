"""Фабрика приложения PySpace IDE."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from flask import Flask, g, request

from .api import register_api
from .auth import bootstrap_admin, current_user
from .config import settings
from .db import close_db, migrate
from .errors import register_error_handlers
from .http import human_size
from .sockets import register_sockets
from .views import register_views

__version__ = "5.0.0"


def create_app() -> Flask:
    settings.ensure_dirs()

    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        SECRET_KEY=settings.secret_key,
        MAX_CONTENT_LENGTH=settings.max_upload_mb * 1024 * 1024,
        JSON_SORT_KEYS=False,
        PERMANENT_SESSION_LIFETIME=dt.timedelta(days=settings.session_days),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=not settings.is_dev,
        SEND_FILE_MAX_AGE_DEFAULT=0 if settings.is_dev else 3600,
        TEMPLATES_AUTO_RELOAD=settings.is_dev,
        SOCK_SERVER_OPTIONS={"ping_interval": 25},
    )

    _configure_logging(app)
    app.teardown_appcontext(close_db)

    with app.app_context():
        version = migrate()
        bootstrap_admin()
        app.logger.info("Схема БД: v%s · данные: %s", version, settings.data_dir)
        if not settings.secret_from_env:
            app.logger.warning(
                "PYSPACE_SECRET не задан — сессии сбросятся при перезапуске. "
                "Задайте переменную окружения на Render."
            )
        if not settings.persistent:
            app.logger.warning(
                "Данные лежат в %s (без Persistent Disk) — на Render они исчезнут "
                "при редеплое. Подключите диск и укажите PYSPACE_DATA_DIR=/data.",
                settings.data_dir,
            )

    register_error_handlers(app)
    register_api(app)
    register_views(app)
    register_sockets(app)

    @app.before_request
    def _touch_user():
        g.request_started = dt.datetime.now(dt.timezone.utc)
        if request.path.startswith("/api/") and request.method != "OPTIONS":
            current_user()

    @app.after_request
    def _security_headers(response):
        if not request.path.startswith("/preview/"):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "same-origin")
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return response

    def _asset_version() -> str:
        """Метка для сброса кэша статики: версия, а в разработке — время правки."""
        if not settings.is_dev:
            return __version__
        root = Path(app.static_folder or "")
        latest = 0.0
        if root.is_dir():
            for item in root.rglob("*"):
                if item.is_file():
                    latest = max(latest, item.stat().st_mtime)
        return f"{__version__}-{int(latest)}"

    @app.context_processor
    def _template_globals():
        return {
            "app_version": __version__,
            "asset_version": _asset_version(),
            "settings": settings,
            "human_size": human_size,
        }

    @app.cli.command("create-admin")
    def create_admin_command():  # pragma: no cover - вспомогательная команда
        """flask create-admin — создать администратора интерактивно."""
        import getpass

        from .auth import validate_password, validate_username
        from .repo import Users

        username = validate_username(input("Логин: ").strip())
        password = validate_password(getpass.getpass("Пароль: "))
        Users.create(username, password, "admin")
        print(f"Администратор {username} создан.")

    return app


def _configure_logging(app: Flask) -> None:
    level = logging.DEBUG if settings.is_dev else logging.INFO
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s · %(message)s"))
    app.logger.handlers = [handler]
    app.logger.setLevel(level)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
