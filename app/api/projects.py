"""Проекты: список, создание, переименование, участники, импорт/экспорт ZIP."""

from __future__ import annotations

import shutil

from flask import Blueprint, request, send_file

from .. import fs_tree
from ..archives import extract_zip, project_name_from_filename, project_zip
from ..auth import login_required, project_access, require_owner, require_user
from ..errors import AppError
from ..http import body, ok
from ..paths import dir_size, project_root
from ..repo import Projects, Users

bp = Blueprint("api_projects", __name__, url_prefix="/api/projects")

TEMPLATES = {"python", "web", "sql", "empty"}


@bp.get("")
@login_required
def list_projects():
    user = require_user()
    projects = Projects.for_user(int(user["id"]))
    for project in projects:
        project["size"] = dir_size(project_root(int(project["id"])))
    return ok(projects=projects)


@bp.post("")
@login_required
def create_project():
    user = require_user()
    data = body()
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 80:
        raise AppError("Название проекта: от 1 до 80 символов.")
    template = str(data.get("template", "python"))
    if template not in TEMPLATES:
        raise AppError("Неизвестный шаблон проекта.")

    project = Projects.create(int(user["id"]), name)
    fs_tree.scaffold(int(project["id"]), template)
    return ok(project=project)


@bp.get("/<int:project_id>")
@login_required
def get_project(project_id: int):
    project = project_access(project_id)
    return ok(
        project={
            "id": project["id"],
            "name": project["name"],
            "access": project["access"],
            "owner_id": project["owner_id"],
            "preview_token": project["preview_token"],
            "created_at": project["created_at"],
            "updated_at": project["updated_at"],
            "size": dir_size(project_root(project_id)),
        },
        members=Projects.members(project_id),
    )


@bp.patch("/<int:project_id>")
@login_required
def rename_project(project_id: int):
    require_owner(project_id)
    user = require_user()
    name = str(body().get("name", "")).strip()
    if not name or len(name) > 80:
        raise AppError("Название проекта: от 1 до 80 символов.")
    Projects.rename(project_id, Projects.unique_name(int(user["id"]), name))
    return ok(name=name)


@bp.delete("/<int:project_id>")
@login_required
def delete_project(project_id: int):
    require_owner(project_id)
    Projects.delete(project_id)
    shutil.rmtree(project_root(project_id), ignore_errors=True)
    return ok(message="Проект удалён.")


# --------------------------------------------------------------------- участники


@bp.post("/<int:project_id>/members")
@login_required
def add_member(project_id: int):
    require_owner(project_id)
    data = body()
    role = str(data.get("role", "editor"))
    if role not in ("editor", "viewer"):
        raise AppError("Роль может быть editor или viewer.")
    target = Users.by_name(str(data.get("username", "")).strip())
    if not target:
        raise AppError("Пользователь не найден.", 404)
    Projects.add_member(project_id, int(target["id"]), role)
    return ok(members=Projects.members(project_id))


@bp.delete("/<int:project_id>/members/<int:user_id>")
@login_required
def remove_member(project_id: int, user_id: int):
    require_owner(project_id)
    Projects.remove_member(project_id, user_id)
    return ok(members=Projects.members(project_id))


# --------------------------------------------------------------------- архивы


@bp.get("/<int:project_id>/archive.zip")
@login_required
def download_project(project_id: int):
    project = project_access(project_id)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in project["name"]).strip()
    return send_file(
        project_zip(project_id),
        as_attachment=True,
        download_name=f"{safe_name or 'project'}.zip",
        mimetype="application/zip",
    )


@bp.post("/import-zip")
@login_required
def import_zip():
    """Создаёт новый проект из загруженного ZIP."""
    user = require_user()
    upload = request.files.get("file")
    if not upload or not (upload.filename or "").lower().endswith(".zip"):
        raise AppError("Нужен файл .zip")

    name = Projects.unique_name(int(user["id"]), project_name_from_filename(upload.filename))
    project = Projects.create(int(user["id"]), name)
    root = project_root(int(project["id"]))
    try:
        files = extract_zip(upload.stream, root)
    except AppError:
        Projects.delete(int(project["id"]))
        shutil.rmtree(root, ignore_errors=True)
        raise
    return ok(project=project, count=len(files), message=f"Проект «{name}» создан, файлов: {len(files)}")


@bp.post("/<int:project_id>/import-zip")
@login_required
def import_zip_into(project_id: int):
    project_access(project_id, write=True)
    upload = request.files.get("file")
    if not upload or not (upload.filename or "").lower().endswith(".zip"):
        raise AppError("Нужен файл .zip")
    target = str(request.form.get("target", "") or "")
    root = project_root(project_id)
    destination = root if not target else fs_tree.project_path(project_id, target)
    destination.mkdir(parents=True, exist_ok=True)
    files = extract_zip(upload.stream, destination)
    Projects.touch(project_id)
    return ok(count=len(files), message=f"Распаковано файлов: {len(files)}")
