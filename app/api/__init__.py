"""Регистрация всех API-блюпринтов."""

from __future__ import annotations

from flask import Flask

from .admin import bp as admin_bp
from .auth import bp as auth_bp
from .drops import bp as drops_bp
from .files import bp as files_bp
from .maintenance import bp as maintenance_bp
from .projects import bp as projects_bp
from .run import bp as run_bp

BLUEPRINTS = (auth_bp, projects_bp, files_bp, run_bp, drops_bp, admin_bp, maintenance_bp)


def register_api(app: Flask) -> None:
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
