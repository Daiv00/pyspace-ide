"""Комнаты обмена (QR-drop): анонимная отправка файлов и текста на сервер."""

from __future__ import annotations

import datetime as dt
import json
import shutil

from flask import Blueprint, request, send_file

from ..auth import login_required, require_user
from ..errors import AppError
from ..http import body, human_size, ok, public_base_url
from ..paths import drop_path, drop_root, normalize_relpath, unique_path
from ..qrcodes import png as qr_png
from ..qrcodes import svg as qr_svg
from ..repo import Drops, ReceivedFiles

bp = Blueprint("api_drops", __name__, url_prefix="/api/drops")

MANIFEST = ".pyspace-manifest.json"


def _drop_url(token: str) -> str:
    return f"{public_base_url()}/d/{token}"


def _write_manifest(token: str) -> None:
    root = drop_root(token)
    items = [
        {"path": item.relative_to(root).as_posix(), "size": item.stat().st_size}
        for item in sorted(root.rglob("*"))
        if item.is_file() and item.name != MANIFEST
    ]
    payload = {
        "token": token,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": items,
    }
    (root / MANIFEST).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------- владелец комнаты


@bp.get("")
@login_required
def my_drops():
    user = require_user()
    drops = Drops.for_user(int(user["id"]))
    for drop in drops:
        drop["url"] = _drop_url(drop["token"])
    return ok(drops=drops)


@bp.post("")
@login_required
def create_drop():
    user = require_user()
    drop = Drops.create(int(user["id"]), str(body().get("label", "")).strip())
    drop_root(drop["token"])
    return ok(
        drop={
            **drop,
            "active": 1,
            "items": 0,
            "url": _drop_url(drop["token"]),
            "qr_png": f"/api/drops/{drop['token']}/qr.png",
            "qr_svg": f"/api/drops/{drop['token']}/qr.svg",
        }
    )


@bp.post("/<token>/revoke")
@login_required
def revoke(token: str):
    user = require_user()
    drop = Drops.by_token(token)
    if not drop or drop["owner_id"] != user["id"]:
        raise AppError("Комната не найдена.", 404)
    Drops.revoke(token)
    return ok(message="Комната закрыта.")


@bp.delete("/<token>")
@login_required
def delete_drop(token: str):
    user = require_user()
    drop = Drops.by_token(token)
    if not drop or drop["owner_id"] != user["id"]:
        raise AppError("Комната не найдена.", 404)
    Drops.delete(token)
    shutil.rmtree(drop_root(token), ignore_errors=True)
    return ok(message="Комната и её файлы удалены.")


# ------------------------------------------------------------------- QR-кода


@bp.get("/<token>/qr.png")
def qr_png_route(token: str):
    if not Drops.active(token):
        raise AppError("Ссылка недействительна.", 404)
    return send_file(qr_png(_drop_url(token)), mimetype="image/png")


@bp.get("/<token>/qr.svg")
def qr_svg_route(token: str):
    if not Drops.active(token):
        raise AppError("Ссылка недействительна.", 404)
    return qr_svg(_drop_url(token)), 200, {"Content-Type": "image/svg+xml"}


# --------------------------------------------------- анонимная сторона комнаты


@bp.get("/<token>")
def drop_info(token: str):
    drop = Drops.active(token)
    if not drop:
        raise AppError("Ссылка недействительна или комната закрыта.", 404)
    root = drop_root(token)
    files = [
        {
            "path": item.relative_to(root).as_posix(),
            "size": item.stat().st_size,
            "size_human": human_size(item.stat().st_size),
        }
        for item in sorted(root.rglob("*"))
        if item.is_file() and item.name != MANIFEST
    ]
    return ok(token=token, label=drop["label"], files=files, url=_drop_url(token))


@bp.post("/<token>/upload")
def drop_upload(token: str):
    drop = Drops.active(token)
    if not drop:
        raise AppError("Ссылка недействительна или комната закрыта.", 404)

    root = drop_root(token)
    saved: list[dict] = []
    problems: list[str] = []

    text = str(request.form.get("text", ""))
    if text.strip():
        name = normalize_relpath(request.form.get("text_name") or "сообщение.txt")
        target = unique_path(drop_path(token, name))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        relative = target.relative_to(root).as_posix()
        ReceivedFiles.add(token, int(drop["owner_id"]), relative, target.name, target.stat().st_size, "text")
        saved.append({"name": target.name, "size": target.stat().st_size})

    for upload in request.files.getlist("files"):
        original = (upload.filename or "").replace("\\", "/").split("/")[-1].strip()
        if not original:
            continue
        try:
            target = unique_path(drop_path(token, original))
            target.parent.mkdir(parents=True, exist_ok=True)
            upload.save(str(target))
            relative = target.relative_to(root).as_posix()
            size = target.stat().st_size
            ReceivedFiles.add(token, int(drop["owner_id"]), relative, original, size, "file")
            saved.append({"name": original, "size": size})
        except Exception as exc:  # noqa: BLE001 - показываем пользователю, что не влезло
            problems.append(f"{original}: {exc}")

    if not saved:
        raise AppError("Не удалось сохранить ни файл, ни текст.", 400, details=problems)

    _write_manifest(token)
    return ok(files=saved, problems=problems, message=f"Отправлено: {len(saved)}")


@bp.get("/<token>/download")
def drop_download(token: str):
    if not Drops.active(token):
        raise AppError("Ссылка недействительна.", 404)
    path = drop_path(token, request.args.get("path", ""))
    if not path.is_file():
        raise AppError("Файл не найден.", 404)
    return send_file(path, as_attachment=True, download_name=path.name)


# ----------------------------------------------------------- хранилище файлов


@bp.get("/vault/files")
@login_required
def vault():
    user = require_user()
    rows = ReceivedFiles.all() if user["role"] == "admin" else ReceivedFiles.visible_to(int(user["id"]))
    for row in rows:
        row["size_human"] = human_size(int(row["size"]))
    return ok(files=rows, is_admin=user["role"] == "admin")


@bp.get("/vault/files/<int:file_id>/download")
@login_required
def vault_download(file_id: int):
    user = require_user()
    record = ReceivedFiles.by_id(file_id)
    if not record:
        raise AppError("Файл не найден.", 404)
    allowed = user["role"] == "admin" or user["id"] in (record["recipient_id"], record["owner_id"])
    if not allowed:
        raise AppError("Нет доступа к этому файлу.", 403)
    path = drop_path(record["drop_token"], record["stored_path"])
    if not path.is_file():
        raise AppError("Файл отсутствует на диске.", 404)
    return send_file(path, as_attachment=True, download_name=record["original_name"])
