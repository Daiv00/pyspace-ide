"""Сессии, декораторы доступа и проверка прав на проект."""

from __future__ import annotations

import re
from functools import wraps
from typing import Any, Callable

from flask import g, session

from .config import settings
from .errors import AppError
from .repo import Projects, Users

USERNAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_.\-]{3,32}")
MIN_PASSWORD = 8


def validate_username(value: str) -> str:
    value = (value or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise AppError("Логин: 3–32 символа, буквы, цифры, точка, дефис или подчёркивание.")
    return value


def validate_password(value: str) -> str:
    if len(value or "") < MIN_PASSWORD:
        raise AppError(f"Пароль должен быть не короче {MIN_PASSWORD} символов.")
    return value


def sign_in(user_id: int) -> None:
    session.clear()
    session["uid"] = int(user_id)
    session.permanent = True


def sign_out() -> None:
    session.clear()


def current_user() -> dict[str, Any] | None:
    """Пользователь текущего запроса (кэшируется в g)."""
    if "current_user" in g:
        return g.current_user

    user_id = session.get("uid")
    user = Users.by_id(int(user_id)) if user_id else None
    g.current_user = dict(user) if user else None
    if g.current_user is None and user_id:
        session.clear()
    return g.current_user


def require_user() -> dict[str, Any]:
    user = current_user()
    if not user:
        raise AppError("Требуется вход в аккаунт.", 401)
    return user


def require_admin() -> dict[str, Any]:
    user = require_user()
    if user["role"] != "admin":
        raise AppError("Нужны права администратора.", 403)
    return user


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args, **kwargs):
        require_user()
        return view(*args, **kwargs)

    return wrapper


def admin_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args, **kwargs):
        require_admin()
        return view(*args, **kwargs)

    return wrapper


def project_access(project_id: int, *, write: bool = False) -> dict[str, Any]:
    """Возвращает проект или бросает 403/404."""
    user = require_user()
    project = Projects.access(int(project_id), int(user["id"]))
    if not project:
        raise AppError("Проект не найден или нет доступа.", 404)
    if write and project["access"] == "viewer":
        raise AppError("У вас доступ только для чтения.", 403)
    return project


def require_owner(project_id: int) -> dict[str, Any]:
    project = project_access(project_id)
    if project["access"] != "owner":
        raise AppError("Действие доступно только владельцу проекта.", 403)
    return project


def bootstrap_admin() -> None:
    """Создаёт/повышает администратора из переменных окружения при старте."""
    if not (settings.admin_user and settings.admin_password):
        return
    existing = Users.by_name(settings.admin_user)
    if existing is None:
        Users.create(settings.admin_user, settings.admin_password, role="admin")
        return
    if existing["role"] != "admin":
        Users.set_role(int(existing["id"]), "admin")
