"""HTML-страницы и отдача предпросмотра."""

from __future__ import annotations

from flask import Flask

from .pages import bp as pages_bp
from .preview import bp as preview_bp


def register_views(app: Flask) -> None:
    app.register_blueprint(pages_bp)
    app.register_blueprint(preview_bp)
