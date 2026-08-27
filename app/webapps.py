"""Запуск веб-приложений проекта (Flask, FastAPI, aiohttp, http.server…).

Кнопка «Запустить» подходит для скриптов: процесс живёт до 20 секунд и его
вывод показывается в панели. Веб-сервер так запустить нельзя — он не
завершается сам, и до его порта никто не может дотянуться из браузера.

Этот модуль держит для каждого проекта один долгоживущий процесс, отдаёт ему
свободный порт в переменной `PORT` и запоминает, куда писать журнал. Наружу
приложение видно через обратный прокси `/live/<токен>/` (см. `views/live.py`).
"""

from __future__ import annotations

import atexit
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import settings
from .errors import AppError
from .paths import project_path, project_root
from .runner import build_env

# Внутри контейнера порты никому не видны, поэтому берём произвольный диапазон.
PORT_RANGE = range(8300, 8400)

_LOCK = threading.Lock()
_APPS: dict[int, "WebApp"] = {}


@dataclass
class WebApp:
    """Один запущенный процесс-сервер проекта."""

    project_id: int
    path: str
    port: int
    process: subprocess.Popen
    log_file: Path
    started_at: float = field(default_factory=time.time)
    mode: str = "python"
    framework: str = "script"

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def log_tail(self, limit: int = 8000) -> str:
        try:
            text = self.log_file.read_text("utf-8", errors="replace")
        except OSError:
            return ""
        return text if len(text) <= limit else "…\n" + text[-limit:]

    def info(self, token: str = "") -> dict[str, Any]:
        return {
            "running": self.alive,
            "path": self.path,
            "port": self.port,
            "pid": self.process.pid,
            "uptime": int(time.time() - self.started_at),
            "returncode": self.process.returncode,
            "mode": self.mode,
            "framework": self.framework,
            "url": f"/live/{token}/" if token else "",
        }


def _log_path(project_id: int) -> Path:
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    return settings.tmp_dir / f"webapp_{int(project_id)}.log"


def _free_port() -> int:
    busy = {app.port for app in _APPS.values() if app.alive}
    for port in PORT_RANGE:
        if port in busy:
            continue
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise AppError("Свободных портов нет — остановите другое веб-приложение.", 503)


# ------------------------------------------------- распознавание веб-фреймворка

# `app = Flask(__name__)` / `api = FastAPI()` — запоминаем имя переменной.
_FLASK_VAR = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(?:flask\.)?Flask\s*\(", re.M)
_FASTAPI_VAR = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(?:fastapi\.)?FastAPI\s*\(", re.M)

# Признаки того, что файл поднимает сервер сам.
_SELF_START = (
    r"\buvicorn\.run\s*\(",
    r"\bserve_forever\s*\(",
    r"\brun_app\s*\(",
    r"\brun_simple\s*\(",
    r"\bsocketio\.run\s*\(",
    r"\bwaitress\.serve\s*\(",
    r"\bhypercorn\b",
)


# Комментарии и строковые литералы: упоминание `app.run()` в тексте — не запуск сервера.
_COMMENT = re.compile(r"#[^\n]*")
_STRINGS = re.compile(r"(\"\"\"|\'\'\')(?:.|\n)*?\1|\"[^\"\n]*\"|\'[^\'\n]*\'")


def _code_only(text: str) -> str:
    """Текст без строк и комментариев — чтобы не принимать упоминание за вызов."""
    return _COMMENT.sub("", _STRINGS.sub('""', text))


def _starts_itself(text: str, variable: str) -> bool:
    """Файл сам вызывает сервер (`app.run(...)`, `uvicorn.run(...)` и т. п.)."""
    text = _code_only(text)
    patterns = list(_SELF_START)
    if variable:
        patterns.append(rf"\b{re.escape(variable)}\.run\s*\(")
    return any(re.search(pattern, text) for pattern in patterns)


def _module_name(relative: str) -> str:
    """`src/main.py` → `src.main` (для `-m uvicorn` и `flask --app`)."""
    parts = [part for part in relative.replace("\\", "/").split("/") if part]
    if not parts:
        return ""
    parts[-1] = re.sub(r"\.py$", "", parts[-1], flags=re.I)
    return ".".join(parts)


def detect(script: Path, relative: str) -> dict[str, Any]:
    """Что перед нами: обычный скрипт, Flask- или FastAPI-приложение."""
    try:
        text = script.read_text("utf-8", errors="replace")[:400_000]
    except OSError:
        return {"kind": "script", "variable": "", "self_start": True, "module": ""}

    code = _code_only(text)
    fastapi_match = _FASTAPI_VAR.search(code)
    flask_match = _FLASK_VAR.search(code)
    if fastapi_match:
        kind, variable = "fastapi", fastapi_match.group(1)
    elif flask_match:
        kind, variable = "flask", flask_match.group(1)
    else:
        kind, variable = "script", ""

    return {
        "kind": kind,
        "variable": variable,
        "self_start": _starts_itself(text, variable),
        "module": _module_name(relative),
    }


def _importable(env: dict[str, str], root: Path, module: str) -> bool:
    """Проверяем, что uvicorn/flask действительно установлены в окружении проекта."""
    try:
        # -P: не подставлять текущую папку в sys.path, иначе файл проекта с именем
        # вроде types.py или code.py перекроет стандартную библиотеку и проверка соврёт.
        probe = subprocess.run(
            [sys.executable, "-P", "-c", f"import {module}"],
            cwd=str(root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _command(
    script: Path, relative: str, port: int, env: dict[str, str], root: Path
) -> tuple[list[str], str, dict[str, Any]]:
    """Команда запуска, название режима и результат распознавания.

    Если файл сам вызывает `app.run()` или `uvicorn.run()` — просто запускаем его.
    Если нет (обычная ситуация для FastAPI и для Flask под gunicorn) — поднимаем
    приложение через наш загрузчик `webapp_boot.py`, чтобы не заставлять править код.
    """
    info = detect(script, relative)
    plain = ([sys.executable, "-u", str(script)], "python", info)

    if info["self_start"] or not info["variable"] or info["kind"] == "script":
        return plain

    module = "uvicorn" if info["kind"] == "fastapi" else "flask"
    if not _importable(env, root, module):
        return plain

    command = [
        # -P: папка загрузчика не попадает в sys.path (иначе перекроет стандартные модули).
        sys.executable, "-u", "-P",
        str(Path(__file__).resolve().parent.parent / "tools" / "webapp_boot.py"),
        str(script), info["variable"], info["kind"], str(port),
    ]
    return command, ("uvicorn" if info["kind"] == "fastapi" else "flask"), info


def _port_open(port: int, timeout: float = 0.4) -> bool:
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _kill(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def get(project_id: int) -> WebApp | None:
    with _LOCK:
        return _APPS.get(int(project_id))


def status(project_id: int, token: str = "") -> dict[str, Any]:
    app = get(project_id)
    if not app:
        return {"running": False, "enabled": settings.enable_webapps, "url": f"/live/{token}/" if token else ""}
    data = app.info(token)
    data["enabled"] = settings.enable_webapps
    if not app.alive:
        data["log"] = app.log_tail(2000)
    return data


def logs(project_id: int, limit: int = 8000) -> str:
    app = get(project_id)
    if app:
        return app.log_tail(limit)
    path = _log_path(project_id)
    if path.is_file():
        try:
            text = path.read_text("utf-8", errors="replace")
        except OSError:
            return ""
        return text if len(text) <= limit else "…\n" + text[-limit:]
    return ""


def start(project_id: int, relative: str, token: str = "") -> dict[str, Any]:
    """Поднимает сервер проекта и ждёт, пока он займёт свой порт."""
    if not settings.enable_webapps:
        raise AppError("Запуск веб-приложений отключён администратором.", 403)

    script = project_path(project_id, relative)
    if not script.is_file():
        raise AppError("Файл не найден.", 404)
    if script.suffix.lower() != ".py":
        raise AppError("Как сервер запускается только файл .py.", 400)

    stop(project_id)

    with _LOCK:
        running = sum(1 for app in _APPS.values() if app.alive)
        if running >= settings.webapp_limit:
            raise AppError(
                f"Одновременно можно держать {settings.webapp_limit} веб-приложения. "
                "Остановите одно из них.",
                429,
            )
        port = _free_port()

    root = project_root(project_id)
    log_file = _log_path(project_id)
    prefix = f"/live/{token}" if token else ""
    env = build_env(
        project_id,
        {
            # Общепринятые переменные: их читают Flask, FastAPI, Django, Node…
            "PORT": str(port),
            "HOST": "0.0.0.0",
            "FLASK_RUN_PORT": str(port),
            "FLASK_RUN_HOST": "0.0.0.0",
            "PYSPACE_WEBAPP": "1",
            "PYSPACE_WEBAPP_PORT": str(port),
            "PYSPACE_WEBAPP_PREFIX": prefix,
            # Корень проекта — чтобы загрузчик webapp_boot.py видел соседние модули.
            "PYSPACE_WEBAPP_ROOT": str(root),
            # Приложение стоит за нашим прокси, а он — за HTTPS Render.
            "FORWARDED_ALLOW_IPS": "*",
        },
    )

    try:
        handle = log_file.open("wb")
    except OSError as exc:  # noqa: BLE001 - диск переполнен или только чтение
        raise AppError("Не удалось создать журнал веб-приложения.", 500) from exc

    kwargs: dict[str, Any] = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # чтобы гасить всё дерево процессов

    command, mode, detected = _command(script, relative, port, env, root)

    try:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
    except OSError as exc:  # noqa: BLE001
        handle.close()
        raise AppError(f"Не удалось запустить процесс: {exc}", 500) from exc
    finally:
        handle.close()

    app = WebApp(
        project_id=int(project_id),
        path=relative,
        port=port,
        process=process,
        log_file=log_file,
        mode=mode,
        framework=str(detected.get("kind") or "script"),
    )
    with _LOCK:
        _APPS[int(project_id)] = app

    deadline = time.time() + settings.webapp_boot_timeout
    while time.time() < deadline:
        if process.poll() is not None:
            with _LOCK:
                _APPS.pop(int(project_id), None)
            return {
                "running": False,
                "path": relative,
                "port": port,
                "error": "Процесс завершился сразу после запуска.",
                "log": app.log_tail(4000),
            }
        if _port_open(port):
            data = app.info(token)
            data["log"] = app.log_tail(4000)
            return data
        time.sleep(0.25)

    # Процесс жив, но порт не занял: возможно, это не сервер или он ещё грузится.
    data = app.info(token)
    data["warning"] = (
        f"Процесс работает, но за {settings.webapp_boot_timeout} с не открыл порт {port}. "
        "Убедитесь, что сервер слушает порт из переменной PORT и адрес 0.0.0.0."
    )
    data["log"] = app.log_tail(4000)
    return data


def stop(project_id: int) -> dict[str, Any]:
    with _LOCK:
        app = _APPS.pop(int(project_id), None)
    if not app:
        return {"running": False, "stopped": False}
    _kill(app.process)
    return {"running": False, "stopped": True, "path": app.path, "log": app.log_tail(2000)}


def stop_all() -> None:
    with _LOCK:
        apps = list(_APPS.values())
        _APPS.clear()
    for app in apps:
        _kill(app.process)


def port_for(project_id: int) -> int | None:
    app = get(project_id)
    if app and app.alive:
        return app.port
    return None


atexit.register(stop_all)
