"""Администрирование: пользователи, статистика, выдача полученных файлов."""

from __future__ import annotations

import shutil

from flask import Blueprint

from ..auth import admin_required, require_admin, validate_password, validate_username
from ..config import settings
from ..errors import AppError
from ..http import body, human_size, ok
from ..paths import drop_path, drop_root
from ..repo import Drops, Projects, ReceivedFiles, Users
from ..db import query_one

bp = Blueprint("api_admin", __name__, url_prefix="/api/admin")


@bp.get("/overview")
@admin_required
def overview():
    users = Users.all()
    projects = query_one("SELECT COUNT(*) AS n FROM projects")
    drops = query_one("SELECT COUNT(*) AS n FROM drops WHERE active = 1")
    received = query_one("SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS bytes FROM received_files")
    return ok(
        stats={
            "users": len(users),
            "admins": sum(1 for user in users if user["role"] == "admin"),
            "projects": int(projects["n"]) if projects else 0,
            "active_drops": int(drops["n"]) if drops else 0,
            "received_files": int(received["n"]) if received else 0,
            "received_bytes_human": human_size(int(received["bytes"]) if received else 0),
        },
        environment={
            "data_dir": str(settings.data_dir),
            "persistent_storage": settings.persistent,
            "terminal": settings.enable_pty,
            "registration": settings.enable_registration,
            "secret_from_env": settings.secret_from_env,
        },
        users=users,
    )


@bp.post("/users")
@admin_required
def create_user():
    data = body()
    username = validate_username(data.get("username", ""))
    password = validate_password(data.get("password", ""))
    role = str(data.get("role", "user"))
    if role not in ("user", "admin"):
        raise AppError("Роль может быть user или admin.")
    Users.create(username, password, role)
    return ok(users=Users.all())


@bp.patch("/users/<int:user_id>")
@admin_required
def update_user(user_id: int):
    admin = require_admin()
    data = body()
    target = Users.by_id(user_id)
    if not target:
        raise AppError("Пользователь не найден.", 404)

    if "role" in data:
        role = str(data["role"])
        if role not in ("user", "admin"):
            raise AppError("Роль может быть user или admin.")
        if target["role"] == "admin" and role == "user" and Users.admin_count() <= 1:
            raise AppError("Нельзя снять права у единственного администратора.")
        Users.set_role(user_id, role)

    if data.get("password"):
        Users.set_password(user_id, validate_password(str(data["password"])))

    return ok(users=Users.all(), self_changed=user_id == admin["id"])


@bp.delete("/users/<int:user_id>")
@admin_required
def delete_user(user_id: int):
    admin = require_admin()
    if user_id == admin["id"]:
        raise AppError("Нельзя удалить собственный аккаунт.")
    target = Users.by_id(user_id)
    if not target:
        raise AppError("Пользователь не найден.", 404)
    if target["role"] == "admin" and Users.admin_count() <= 1:
        raise AppError("Нельзя удалить единственного администратора.")

    from ..paths import project_root

    for project in Projects.for_user(user_id):
        if project["owner_id"] == user_id:
            shutil.rmtree(project_root(int(project["id"])), ignore_errors=True)
    for drop in Drops.for_user(user_id):
        shutil.rmtree(drop_root(drop["token"]), ignore_errors=True)

    Users.delete(user_id)
    return ok(users=Users.all())


@bp.post("/vault/files/<int:file_id>/assign")
@admin_required
def assign_file(file_id: int):
    if not ReceivedFiles.by_id(file_id):
        raise AppError("Файл не найден.", 404)
    username = str(body().get("username", "")).strip()
    if not username:
        ReceivedFiles.assign(file_id, None)
        return ok(message="Доступ снят.")
    target = Users.by_name(username)
    if not target:
        raise AppError("Пользователь не найден.", 404)
    ReceivedFiles.assign(file_id, int(target["id"]))
    return ok(message=f"Файл выдан пользователю {target['username']}.")


@bp.delete("/vault/files/<int:file_id>")
@admin_required
def delete_file(file_id: int):
    record = ReceivedFiles.by_id(file_id)
    if not record:
        raise AppError("Файл не найден.", 404)
    try:
        drop_path(record["drop_token"], record["stored_path"]).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - запись удаляем даже если файла уже нет
        pass
    ReceivedFiles.delete(file_id)
    return ok(message="Файл удалён.")
