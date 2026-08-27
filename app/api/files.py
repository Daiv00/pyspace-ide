"""Файлы и папки проекта: дерево, чтение, запись, перемещение, загрузка."""

from __future__ import annotations

from flask import Blueprint, request, send_file

from .. import fs_tree
from ..archives import folder_zip, project_zip
from ..auth import login_required, project_access
from ..errors import AppError
from ..http import body, ok
from ..paths import project_path
from ..repo import Projects

bp = Blueprint("api_files", __name__, url_prefix="/api/projects/<int:project_id>")


@bp.get("/tree")
@login_required
def tree(project_id: int):
    project_access(project_id)
    return ok(tree=fs_tree.list_tree(project_id))


@bp.get("/search")
@login_required
def search(project_id: int):
    project_access(project_id)
    return ok(
        hits=fs_tree.search(
            project_id,
            request.args.get("q", ""),
            request.args.get("case") == "1",
        )
    )


@bp.get("/file")
@login_required
def read(project_id: int):
    project_access(project_id)
    return ok(file=fs_tree.read_file(project_id, request.args.get("path", "")))


@bp.put("/file")
@login_required
def save(project_id: int):
    project_access(project_id, write=True)
    data = body()
    result = fs_tree.write_file(project_id, data.get("path", ""), str(data.get("content", "")))
    Projects.touch(project_id)
    return ok(**result)


@bp.post("/file")
@login_required
def create(project_id: int):
    project_access(project_id, write=True)
    data = body()
    kind = str(data.get("type", "file"))
    path = data.get("path", "")
    result = fs_tree.create_dir(project_id, path) if kind == "dir" else fs_tree.create_file(
        project_id, path, str(data.get("content", ""))
    )
    Projects.touch(project_id)
    return ok(**result, type=kind)


@bp.post("/move")
@login_required
def move(project_id: int):
    project_access(project_id, write=True)
    data = body()
    result = fs_tree.move(project_id, data.get("from", ""), data.get("to", ""))
    Projects.touch(project_id)
    return ok(**result)


@bp.post("/copy")
@login_required
def copy(project_id: int):
    project_access(project_id, write=True)
    data = body()
    result = fs_tree.copy(project_id, data.get("from", ""), data.get("to", ""))
    Projects.touch(project_id)
    return ok(**result)


@bp.delete("/file")
@login_required
def delete(project_id: int):
    project_access(project_id, write=True)
    result = fs_tree.delete(project_id, body().get("path", ""))
    Projects.touch(project_id)
    return ok(**result)


@bp.post("/upload")
@login_required
def upload(project_id: int):
    project_access(project_id, write=True)
    files = request.files.getlist("files")
    if not files:
        raise AppError("Файлы не выбраны.")
    saved = fs_tree.save_uploads(project_id, files, str(request.form.get("target", "") or ""))
    Projects.touch(project_id)
    return ok(files=saved, message=f"Загружено файлов: {len(saved)}")


@bp.get("/download")
@login_required
def download(project_id: int):
    """Отдаёт файл как есть, а папку — упакованной в ZIP."""
    project_access(project_id)
    relative = request.args.get("path", "")
    path = project_path(project_id, relative, allow_empty=True)
    if path.is_file():
        return send_file(path, as_attachment=True, download_name=path.name)
    if not relative.strip("/ "):
        # Пустой путь — весь проект целиком, без лишней папки внутри архива.
        return send_file(
            project_zip(project_id),
            mimetype="application/zip",
            as_attachment=True,
            download_name="project.zip",
        )
    if path.is_dir():
        return send_file(
            folder_zip(path, path.name),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{path.name or 'folder'}.zip",
        )
    raise AppError("Файл не найден.", 404)
