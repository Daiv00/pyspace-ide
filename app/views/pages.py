"""Страницы: сама IDE, страница комнаты обмена, health-check."""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, url_for

from ..auth import current_user
from ..config import settings
from ..db import migrate
from ..repo import Drops, Users

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    user = current_user()
    return render_template(
        "ide.html",
        boot={
            "authenticated": bool(user),
            "user": {"id": user["id"], "username": user["username"], "role": user["role"]}
            if user
            else None,
            "features": {
                "registration": settings.enable_registration or Users.count() == 0,
                "terminal": settings.enable_pty,
                "preview": settings.enable_preview,
                "persistent_storage": settings.persistent,
            },
            "limits": {
                "max_upload_mb": settings.max_upload_mb,
                "max_file_kb": settings.max_file_kb,
                "run_timeout": settings.run_timeout,
            },
        },
    )


@bp.get("/d/<token>")
def drop_page(token: str):
    drop = Drops.active(token)
    if not drop:
        return render_template("drop.html", token=token, invalid=True), 404
    return render_template("drop.html", token=token, label=drop["label"], invalid=False)


@bp.get("/s/<token>")
def legacy_drop(token: str):
    """Совместимость со старыми короткими ссылками PySpace."""
    return redirect(url_for("pages.drop_page", token=token), code=301)


@bp.get("/share/<token>")
def legacy_share(token: str):
    return redirect(url_for("pages.drop_page", token=token), code=301)


@bp.get("/healthz")
def healthz():
    return jsonify(status="ok", schema=migrate(), persistent=settings.persistent)


@bp.get("/health")
def health():
    return "ok", 200


@bp.get("/robots.txt")
def robots():
    return "User-agent: *\nDisallow: /preview/\nDisallow: /d/\n", 200, {"Content-Type": "text/plain"}
