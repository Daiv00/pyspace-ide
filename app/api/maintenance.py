"""Обслуживание: состояние самопинга и резервные копии данных."""

from __future__ import annotations

from flask import Blueprint

from .. import backup, keepalive
from ..auth import admin_required
from ..config import settings
from ..errors import AppError
from ..http import human_size, ok

bp = Blueprint("api_maintenance", __name__, url_prefix="/api/maintenance")


@bp.get("/status")
@admin_required
def status():
    info = backup.status()
    return ok(
        keepalive=keepalive.status(),
        backup=info,
        persistent=settings.persistent,
        last_backup_size_human=(
            human_size(int(info["last_backup_size"])) if info.get("last_backup_size") else None
        ),
    )


@bp.post("/backup")
@admin_required
def make_backup():
    try:
        result = backup.backup_now(force=True)
    except Exception as error:
        raise AppError(str(error), 400) from error
    return ok(
        result=result,
        size_human=human_size(int(result.get("size", 0))) if result.get("size") else None,
        backup=backup.status(),
    )


@bp.post("/restore")
@admin_required
def do_restore():
    try:
        result = backup.restore_now()
    except Exception as error:
        raise AppError(str(error), 400) from error
    if not result.get("found"):
        raise AppError("В репозитории пока нет ни одной копии.", 404)
    return ok(result=result, backup=backup.status())
