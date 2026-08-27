"""Живой предпросмотр веб-проектов.

Файлы проекта отдаются по секретному токену на `/preview/<token>/<путь>`, так
что HTML, CSS, JS, картинки и fetch внутри проекта работают как на обычном
хостинге. Документ принудительно помещается в песочницу через CSP `sandbox`,
поэтому код проекта не может дотянуться до сессии IDE.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from flask import Blueprint, Response, abort, redirect, request, send_file

from ..config import settings
from ..errors import AppError
from ..paths import project_path, project_root
from ..repo import Projects

bp = Blueprint("preview", __name__, url_prefix="/preview")

INDEX_CANDIDATES = ("index.html", "index.htm", "main.html")

SANDBOX_CSP = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads"

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("image/svg+xml", ".svg")


def _harden(response: Response) -> Response:
    response.headers["Content-Security-Policy"] = SANDBOX_CSP
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers.pop("X-Frame-Options", None)
    return response


def _project_or_404(token: str) -> dict:
    if not settings.enable_preview:
        raise AppError("Предпросмотр отключён.", 403)
    project = Projects.by_preview_token(token)
    if not project:
        abort(404)
    return project


def _resolve(project_id: int, relative: str) -> Path:
    root = project_root(project_id)
    target = project_path(project_id, relative, allow_empty=True)
    if target.is_dir():
        for candidate in INDEX_CANDIDATES:
            if (target / candidate).is_file():
                return target / candidate
        listing = _directory_listing(target, root)
        raise _Listing(listing)
    if not target.is_file():
        abort(404)
    return target


class _Listing(Exception):
    def __init__(self, html: str) -> None:
        super().__init__("directory listing")
        self.html = html


def _directory_listing(folder: Path, root: Path) -> str:
    relative = folder.relative_to(root).as_posix()
    rows = []
    for item in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if item.name.startswith(".") or item.name in ("__pycache__", "node_modules"):
            continue
        suffix = "/" if item.is_dir() else ""
        href = f"{item.name}{suffix}"
        rows.append(f'<li><a href="{href}">{item.name}{suffix}</a></li>')
    body = "".join(rows) or "<li><em>папка пуста</em></li>"
    return (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>PySpace preview</title><style>"
        "body{font:15px/1.6 system-ui,sans-serif;background:#0f1117;color:#e8ecf4;padding:32px}"
        "h1{font-size:15px;color:#9aa4b8;font-weight:500;margin:0 0 16px}"
        "ul{list-style:none;padding:0;display:grid;gap:6px;max-width:560px}"
        "li{background:#171a24;border:1px solid #262b38;border-radius:10px}"
        "a{display:block;padding:11px 14px;color:#bda7ff;text-decoration:none}"
        "a:hover{background:#1e2230}</style></head><body>"
        f"<h1>PySpace preview · /{relative}</h1><ul>{body}</ul></body></html>"
    )


@bp.get("/<token>")
def preview_root(token: str):
    _project_or_404(token)
    return redirect(f"/preview/{token}/", code=302)


@bp.get("/<token>/", defaults={"path": ""})
@bp.get("/<token>/<path:path>")
def preview_file(token: str, path: str):
    project = _project_or_404(token)
    project_id = int(project["id"])
    try:
        target = _resolve(project_id, path)
    except _Listing as listing:
        return _harden(Response(listing.html, mimetype="text/html; charset=utf-8"))

    mime, _ = mimetypes.guess_type(target.name)
    if mime is None:
        mime = "text/plain"
    needs_charset = mime.startswith("text/") or mime in ("application/json", "image/svg+xml")

    response = send_file(target, mimetype=mime, conditional=True)
    # send_file сам добавляет charset только текстовым типам, поэтому задаём его один раз.
    response.headers["Content-Type"] = f"{mime}; charset=utf-8" if needs_charset else mime
    return _harden(response)


@bp.get("/<token>/__meta")
def preview_meta(token: str):
    project = _project_or_404(token)
    root = project_root(int(project["id"]))
    entries = sorted(
        item.relative_to(root).as_posix()
        for item in root.rglob("*.html")
        if item.is_file()
    )
    latest = max(
        (item.stat().st_mtime for item in root.rglob("*") if item.is_file()),
        default=0,
    )
    return {
        "ok": True,
        "project": project["name"],
        "pages": entries[:100],
        "updated_at": int(latest),
        "requested_by": request.remote_addr,
    }
