"""Запуск кода, pip и служебная информация о терминале."""

from __future__ import annotations

from flask import Blueprint

from .. import runner
from ..auth import login_required, project_access
from ..config import settings
from ..http import body, ok

bp = Blueprint("api_run", __name__, url_prefix="/api/projects/<int:project_id>")


@bp.post("/run")
@login_required
def run(project_id: int):
    project_access(project_id)
    data = body()
    result = runner.run_file(
        project_id,
        str(data.get("path", "main.py")),
        str(data.get("stdin", "")),
    )
    return ok(result=result)


@bp.post("/pip")
@login_required
def pip(project_id: int):
    project_access(project_id, write=True)
    return ok(result=runner.pip_install(project_id, str(body().get("package", ""))))


@bp.get("/pip")
@login_required
def pip_installed(project_id: int):
    project_access(project_id)
    return ok(result=runner.pip_list(project_id))


@bp.get("/terminal")
@login_required
def terminal_info(project_id: int):
    project_access(project_id, write=True)
    return ok(
        enabled=settings.enable_pty,
        websocket=f"/ws/terminal/{project_id}",
        shell="bash",
    )
