"""Управление веб-приложением проекта: старт, остановка, журнал."""

from __future__ import annotations

from typing import Any

from flask import Blueprint

from .. import webapps
from ..auth import login_required, project_access
from ..http import body, ok

bp = Blueprint("api_webapps", __name__, url_prefix="/api/projects/<int:project_id>/webapp")


def _token(project: dict[str, Any]) -> str:
    return str(project.get("preview_token") or "")


@bp.get("")
@login_required
def webapp_status(project_id: int):
    project = project_access(project_id)
    return ok(webapp=webapps.status(project_id, _token(project)))


@bp.post("/start")
@login_required
def webapp_start(project_id: int):
    project = project_access(project_id, write=True)
    path = str(body().get("path", "app.py"))
    return ok(webapp=webapps.start(project_id, path, _token(project)))


@bp.post("/stop")
@login_required
def webapp_stop(project_id: int):
    project_access(project_id, write=True)
    return ok(webapp=webapps.stop(project_id))


@bp.get("/logs")
@login_required
def webapp_logs(project_id: int):
    project_access(project_id)
    return ok(log=webapps.logs(project_id))
