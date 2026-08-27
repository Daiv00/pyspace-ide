"""Самопинг: не даёт бесплатному сервису Render заснуть.

Render останавливает бесплатный веб-сервис после 15 минут без ВХОДЯЩЕГО трафика.
Запрос на 127.0.0.1 таким трафиком не считается, поэтому фоновый поток дёргает
собственный публичный адрес.

Адрес ищется в три приёма, чтобы самопинг работал без ручной настройки:

1. `PYSPACE_PUBLIC_URL` — если вы задали его сами;
2. `RENDER_EXTERNAL_URL` — Render подставляет его в окружение сервиса;
3. первый входящий запрос — из него берётся реальный адрес сайта
   (учитывая `X-Forwarded-Proto`/`Host` от прокси Render).

Третий пункт важен: если сервис создан вручную, а не по `render.yaml`,
переменных может не быть вовсе — раньше самопинг в этом случае молча не работал.

Важно: если сервис всё же успел заснуть, поток внутри него тоже остановлен —
разбудить может только настоящий посетитель. Поэтому интервал берём с запасом.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import random
import threading
import time
import urllib.error
import urllib.request

from .config import settings

log = logging.getLogger("pyspace.keepalive")

# Локальные адреса пинговать бессмысленно: Render видит только внешний трафик.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]")

_state: dict[str, object] = {
    "enabled": False,
    "url": None,
    "interval": 0,
    "source": None,
    "reason": "не запущен",
    "last_at": None,
    "last_status": None,
    "last_error": None,
    "count": 0,
    "fails": 0,
}
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _clean(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = f"https://{url}"
    return url


def env_base_url() -> tuple[str, str]:
    """Публичный адрес из переменных окружения и его источник."""
    explicit = _clean(os.getenv("PYSPACE_PUBLIC_URL", ""))
    if explicit:
        return explicit, "PYSPACE_PUBLIC_URL"
    render = _clean(os.getenv("RENDER_EXTERNAL_URL", ""))
    if render:
        return render, "RENDER_EXTERNAL_URL"
    return "", ""


def public_base_url() -> str:
    """Адрес, который используется для пинга (в том числе выученный из запроса)."""
    with _lock:
        url = str(_state.get("url") or "")
    if url:
        base = url.split(settings.keepalive_path)[0]
        if base:
            return base.rstrip("/")
    return env_base_url()[0]


def status() -> dict:
    with _lock:
        return dict(_state)


def _is_local(url: str) -> bool:
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return host.lower() in _LOCAL_HOSTS


def _ping(url: str) -> dict:
    """Один запрос к своему публичному адресу."""
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "pyspace-keepalive/2.0", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            code = int(response.status)
            response.read(256)  # соединение нужно закрыть аккуратно
        with _lock:
            _state["last_status"] = code
            _state["last_error"] = None
            _state["last_at"] = _now()
            _state["count"] = int(_state["count"] or 0) + 1
            _state["fails"] = 0
        log.debug("Самопинг %s → %s", url, code)
        return {"ok": True, "status": code}
    except urllib.error.HTTPError as error:
        # Ответ есть — значит сервис жив, а это главное.
        with _lock:
            _state["last_status"] = int(error.code)
            _state["last_error"] = None
            _state["last_at"] = _now()
            _state["count"] = int(_state["count"] or 0) + 1
            _state["fails"] = 0
        return {"ok": True, "status": int(error.code)}
    except Exception as error:  # noqa: BLE001 - сеть может отвалиться, падать нельзя
        with _lock:
            _state["last_status"] = None
            _state["last_error"] = str(error)[:200]
            _state["last_at"] = _now()
            _state["fails"] = int(_state["fails"] or 0) + 1
        log.warning("Самопинг не удался: %s", error)
        return {"ok": False, "error": str(error)[:200]}


def ping_now() -> dict:
    """Пинг по требованию (кнопка «Проверить» в разделе «Обслуживание»)."""
    url = str(_state.get("url") or "")
    if not url:
        base, _ = env_base_url()
        if not base:
            return {"ok": False, "error": "Публичный адрес пока не известен."}
        url = f"{base}{settings.keepalive_path}"
    return _ping(url)


def remember_url(url: str, source: str = "адрес запроса") -> bool:
    """Запомнить публичный адрес и запустить пинг, если он ещё не работает."""
    candidate = _clean(url)
    if not candidate or _is_local(candidate):
        return False
    return _launch(f"{candidate}{settings.keepalive_path}", source)


def _launch(url: str, source: str) -> bool:
    """Поднять поток пинга. Возвращает False, если он уже работает."""
    global _thread

    with _lock:
        if _thread and _thread.is_alive():
            return False
        interval = max(60, settings.keepalive_interval)
        _state.update(
            {
                "enabled": True,
                "url": url,
                "interval": interval,
                "source": source,
                "reason": "работает",
            }
        )

        def loop() -> None:
            time.sleep(15)  # дать серверу подняться
            while True:
                _ping(url)
                # небольшой разброс, чтобы запросы не били строго в одну секунду
                time.sleep(interval + random.uniform(0, 20))

        _thread = threading.Thread(target=loop, name="pyspace-keepalive", daemon=True)
        _thread.start()
    log.info("Самопинг включён (%s): %s каждые %s с", source, url, max(60, settings.keepalive_interval))
    return True


def start(app) -> None:
    """Включить самопинг (вызывается один раз из create_app)."""
    if not settings.enable_keepalive:
        with _lock:
            _state.update({"enabled": False, "reason": "выключен переменной PYSPACE_KEEPALIVE=0"})
        return

    base, source = env_base_url()
    if base and not _is_local(base):
        _launch(f"{base}{settings.keepalive_path}", source)
        return

    # Адреса нет (или он локальный) — выучим его из первого входящего запроса.
    with _lock:
        _state.update(
            {
                "enabled": True,
                "reason": "ждём первого запроса, чтобы узнать адрес сайта",
                "source": None,
            }
        )
    app.logger.info("Самопинг: адрес узнаем из первого входящего запроса.")

    @app.before_request
    def _learn_public_url():  # noqa: ANN202 - хук Flask
        from flask import request

        with _lock:
            if _thread and _thread.is_alive():
                return None
        remember_url(request.host_url, "адрес запроса")
        return None
