"""Мелкие помощники для HTTP-слоя."""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from .errors import AppError


def body() -> dict[str, Any]:
    """JSON-тело запроса; пустой словарь, если тела нет."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def field(name: str, *, required: bool = True, default: str = "", max_len: int = 4000) -> str:
    value = body().get(name, default)
    text = "" if value is None else str(value)
    if required and not text.strip():
        raise AppError(f"Не заполнено поле «{name}».")
    if len(text) > max_len:
        raise AppError(f"Поле «{name}» слишком длинное.")
    return text


def ok(**payload: Any):
    return jsonify({"ok": True, **payload})


def public_base_url() -> str:
    """Внешний адрес сервиса с учётом прокси Render."""
    scheme = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    host = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
    if not scheme:
        scheme = "https" if request.is_secure else "http"
    if not host:
        host = request.host
    return f"{scheme}://{host}"


def human_size(value: int) -> str:
    number = float(value or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if number < 1024 or unit == "ГБ":
            return f"{number:.0f} {unit}" if unit == "Б" else f"{number:.1f} {unit}"
        number /= 1024
    return f"{number:.1f} ГБ"
