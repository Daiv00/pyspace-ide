"""Регистрация, вход, выход, профиль."""

from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import (
    current_user,
    login_required,
    require_user,
    sign_in,
    sign_out,
    validate_password,
    validate_username,
)
from ..config import settings
from ..errors import AppError
from ..http import body, ok
from ..repo import Users

bp = Blueprint("api_auth", __name__, url_prefix="/api/auth")


def _profile(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


@bp.get("/session")
def session_info():
    user = current_user()
    return jsonify(
        {
            "ok": True,
            "authenticated": bool(user),
            "user": _profile(user) if user else None,
            "features": {
                "registration": settings.enable_registration,
                "terminal": settings.enable_pty,
                "preview": settings.enable_preview,
                "persistent_storage": settings.persistent,
            },
            "limits": {
                "max_upload_mb": settings.max_upload_mb,
                "max_file_kb": settings.max_file_kb,
                "run_timeout": settings.run_timeout,
            },
        }
    )


@bp.post("/register")
def register():
    data = body()
    if not settings.enable_registration and Users.count() > 0:
        raise AppError("Регистрация закрыта. Попросите администратора создать аккаунт.", 403)

    username = validate_username(data.get("username", ""))
    password = validate_password(data.get("password", ""))
    role = "admin" if Users.count() == 0 else "user"
    user_id = Users.create(username, password, role)
    sign_in(user_id)
    return ok(user=_profile(dict(Users.by_id(user_id))), first_admin=role == "admin")


@bp.post("/login")
def login():
    data = body()
    user = Users.verify(str(data.get("username", "")).strip(), str(data.get("password", "")))
    if not user:
        raise AppError("Неверный логин или пароль.", 401)
    sign_in(int(user["id"]))
    Users.touch(int(user["id"]))
    return ok(user=_profile(dict(user)))


@bp.post("/logout")
def logout():
    sign_out()
    return ok()


@bp.post("/password")
@login_required
def change_password():
    user = require_user()
    data = body()
    if not Users.verify(user["username"], str(data.get("current", ""))):
        raise AppError("Текущий пароль указан неверно.", 403)
    Users.set_password(int(user["id"]), validate_password(data.get("password", "")))
    return ok(message="Пароль обновлён.")
