"""Единый формат ошибок: все API отвечают JSON вида {"ok": false, "error": "..."}."""

from __future__ import annotations

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from .config import settings


class AppError(Exception):
    """Ожидаемая, показываемая пользователю ошибка."""

    def __init__(self, message: str, status: int = 400, **extra) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra


def wants_json() -> bool:
    if request.path.startswith("/api/"):
        return True
    return request.accept_mimetypes.best == "application/json"


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def _app_error(exc: AppError):
        payload = {"ok": False, "error": exc.message, **exc.extra}
        if wants_json():
            return jsonify(payload), exc.status
        return render_template("error.html", code=exc.status, message=exc.message), exc.status

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(_exc):
        limit = settings.max_upload_mb
        message = f"Файл слишком большой. Максимум — {limit} МБ."
        return jsonify(ok=False, error=message), 413

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        message = exc.description or exc.name
        if wants_json():
            return jsonify(ok=False, error=message), exc.code or 500
        return render_template("error.html", code=exc.code, message=message), exc.code or 500

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        app.logger.exception("Необработанная ошибка: %s", exc)
        message = str(exc) if settings.is_dev else "Внутренняя ошибка сервера."
        if wants_json():
            return jsonify(ok=False, error=message), 500
        return render_template("error.html", code=500, message=message), 500
