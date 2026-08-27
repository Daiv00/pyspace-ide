"""Самопинг: не даёт бесплатному сервису Render заснуть.

Render останавливает бесплатный веб-сервис после 15 минут без ВХОДЯЩЕГО трафика.
Запрос на 127.0.0.1 таким трафиком не считается, поэтому фоновый поток дёргает
собственный публичный адрес (`RENDER_EXTERNAL_URL` подставляет Render сам).

Важно: если сервис всё же успел заснуть, поток внутри него тоже остановлен —
разбудить может только настоящий посетитель. Поэтому интервал берём с запасом.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import time

import requests

from .config import settings

log = logging.getLogger("pyspace.keepalive")

_state: dict[str, object] = {
    "enabled": False,
    "url": None,
    "interval": 0,
    "last_at": None,
    "last_status": None,
    "last_error": None,
    "count": 0,
}
_thread: threading.Thread | None = None
_lock = threading.Lock()


def public_base_url() -> str:
    """Публичный адрес сервиса без слэша в конце."""
    explicit = os.getenv("PYSPACE_PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    # Render сам прокидывает эту переменную в окружение сервиса.
    return os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")


def status() -> dict:
    with _lock:
        return dict(_state)


def _ping(url: str) -> None:
    try:
        response = requests.get(
            url,
            timeout=45,
            headers={"User-Agent": "pyspace-keepalive/1.0"},
        )
        with _lock:
            _state["last_status"] = response.status_code
            _state["last_error"] = None
            _state["last_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            _state["count"] = int(_state["count"] or 0) + 1
        log.debug("Самопинг %s → %s", url, response.status_code)
    except Exception as error:  # сеть может отвалиться — это не повод падать
        with _lock:
            _state["last_status"] = None
            _state["last_error"] = str(error)[:200]
            _state["last_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        log.warning("Самопинг не удался: %s", error)


def start(app) -> None:
    """Поднять фоновый поток самопинга (вызывается один раз из create_app)."""
    global _thread

    if not settings.enable_keepalive:
        return
    if _thread and _thread.is_alive():
        return

    base = public_base_url()
    if not base:
        app.logger.info(
            "Самопинг выключен: не известен публичный адрес. "
            "На Render он берётся из RENDER_EXTERNAL_URL, локально задайте PYSPACE_PUBLIC_URL."
        )
        return

    url = f"{base}{settings.keepalive_path}"
    interval = max(60, settings.keepalive_interval)

    with _lock:
        _state.update({"enabled": True, "url": url, "interval": interval})

    def loop() -> None:
        time.sleep(20)  # дать серверу подняться
        while True:
            _ping(url)
            time.sleep(interval)

    _thread = threading.Thread(target=loop, name="pyspace-keepalive", daemon=True)
    _thread.start()
    app.logger.info("Самопинг включён: %s каждые %s с", url, interval)
