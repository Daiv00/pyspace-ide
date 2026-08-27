"""Обратный прокси к веб-приложению проекта.

Процесс проекта слушает порт внутри контейнера, наружу его отдаём по адресу
`/live/<токен>/…`. Прокси добавляет заголовки `X-Forwarded-*`, чтобы фреймворк
знал настоящую схему, хост и префикс пути, и подправляет `Location` и
`Set-Cookie` у приложений, которые про префикс не знают.

Ограничение: через прокси идёт только HTTP. WebSocket внутри проекта работать
не будет — для него нужен отдельный порт наружу, чего бесплатный Render не даёт.
"""

from __future__ import annotations

import re

import requests
from flask import Blueprint, Response, abort, redirect, request, stream_with_context

from .. import webapps
from ..config import settings
from ..errors import AppError
from ..repo import Projects

bp = Blueprint("live", __name__, url_prefix="/live")

# Заголовки, которые нельзя пересылать: они описывают конкретное соединение.
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

TIMEOUT = (5, 120)  # соединение, чтение


def _project_or_404(token: str) -> dict:
    if not settings.enable_webapps:
        raise AppError("Запуск веб-приложений отключён.", 403)
    project = Projects.by_preview_token(token)
    if not project:
        abort(404)
    return project


def _not_running(token: str) -> Response:
    html = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>PySpace · сервер не запущен</title><style>"
        "body{font:15px/1.6 system-ui,sans-serif;background:#0f1117;color:#e8ecf4;padding:36px}"
        "h1{font-size:17px;margin:0 0 12px}p{color:#9aa4b8;max-width:52ch}"
        "code{background:#171a24;border:1px solid #262b38;border-radius:6px;padding:2px 6px}"
        "</style></head><body><h1>Сервер проекта не запущен</h1>"
        "<p>Откройте файл сервера в IDE и нажмите <code>Запустить сервер</code>. "
        "Приложение должно слушать порт из переменной <code>PORT</code> и адрес "
        "<code>0.0.0.0</code>.</p></body></html>"
    )
    return Response(html, status=503, mimetype="text/html; charset=utf-8")


def _forward_headers(token: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP
    }
    headers["X-Forwarded-For"] = request.headers.get(
        "X-Forwarded-For", request.remote_addr or "127.0.0.1"
    )
    headers["X-Forwarded-Proto"] = request.headers.get("X-Forwarded-Proto", request.scheme)
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Prefix"] = f"/live/{token}"
    headers["X-Script-Name"] = f"/live/{token}"
    # Сжатие пусть решает наш ответ, а не приложение внутри.
    headers.pop("Accept-Encoding", None)
    cookie = headers.pop("Cookie", None)
    if cookie:
        cleaned = _clean_cookie_header(cookie)
        if cleaned:
            headers["Cookie"] = cleaned
    return headers


def _fix_location(value: str, prefix: str) -> str:
    if value.startswith("/") and not value.startswith(prefix):
        return prefix + value
    return value


_COOKIE_PATH = re.compile(r"(;\s*[Pp]ath=)(/[^;]*)")


def _fix_cookie(value: str, prefix: str) -> str:
    """Подставить префикс в Path, не удваивая его, если приложение уже знает о нём."""
    if "path=" not in value.lower():
        return value + f"; Path={prefix}/"

    def repl(match: re.Match[str]) -> str:
        path = match.group(2)
        if path.startswith(prefix):
            return match.group(1) + path
        return match.group(1) + prefix + path

    return _COOKIE_PATH.sub(repl, value, count=1)


# Cookie самой IDE не должны попадать в приложение проекта.
_OWN_COOKIES = {"pyspace_session"}


def _clean_cookie_header(raw: str) -> str:
    parts = []
    for chunk in raw.split(";"):
        name = chunk.strip().split("=", 1)[0]
        if name and name not in _OWN_COOKIES:
            parts.append(chunk.strip())
    return "; ".join(parts)


@bp.route("/<token>", methods=["GET"])
def live_root(token: str):
    _project_or_404(token)
    return redirect(f"/live/{token}/", code=302)


@bp.route("/<token>/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@bp.route("/<token>/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def live_proxy(token: str, path: str):
    project = _project_or_404(token)
    port = webapps.port_for(int(project["id"]))
    if not port:
        return _not_running(token)

    prefix = f"/live/{token}"
    target = f"http://127.0.0.1:{port}/{path}"

    try:
        upstream = requests.request(
            request.method,
            target,
            params=request.args.to_dict(flat=False),
            headers=_forward_headers(token),
            data=request.get_data(),
            cookies=None,
            allow_redirects=False,
            stream=True,
            timeout=TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        return _not_running(token)
    except requests.exceptions.Timeout:
        return Response(
            "Приложение проекта не ответило за 120 секунд.",
            status=504,
            mimetype="text/plain; charset=utf-8",
        )

    def body():
        try:
            for chunk in upstream.raw.stream(64 * 1024, decode_content=False):
                yield chunk
        finally:
            upstream.close()

    response = Response(stream_with_context(body()), status=upstream.status_code)
    for key, value in upstream.raw.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP:
            continue
        if lower == "location":
            response.headers[key] = _fix_location(value, prefix)
        elif lower == "set-cookie":
            response.headers.add(key, _fix_cookie(value, prefix))
        elif lower in ("x-frame-options", "content-security-policy"):
            continue  # иначе приложение не покажется в iframe предпросмотра
        else:
            response.headers[key] = value
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
