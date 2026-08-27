"""Проверки распознавания веб-фреймворков и самопинга.

Запуск: PYSPACE_SECRET=test .venv/bin/python tests/test_autoserver.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PYSPACE_SECRET", "test-secret")
os.environ.setdefault("PYSPACE_ENV", "development")

from app import webapps  # noqa: E402
from app import keepalive  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def write(folder: Path, name: str, code: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


def test_detect(folder: Path) -> None:
    print("Распознавание фреймворка:")

    flask_plain = write(folder, "site.py", "from flask import Flask\napp = Flask(__name__)\n")
    info = webapps.detect(flask_plain, "site.py")
    check(info["kind"] == "flask", "Flask без app.run() определяется как flask")
    check(info["variable"] == "app", "имя переменной приложения найдено")
    check(info["self_start"] is False, "файл без app.run() не запускает сервер сам")
    check(info["module"] == "site", "имя модуля для flask --app посчитано")

    flask_self = write(
        folder,
        "self_run.py",
        "from flask import Flask\nsrv = Flask(__name__)\nif __name__ == '__main__':\n    srv.run(port=5000)\n",
    )
    info = webapps.detect(flask_self, "self_run.py")
    check(info["self_start"] is True, "srv.run() считается самостоятельным запуском")

    fastapi_app = write(folder, "pkg/main.py", "from fastapi import FastAPI\napi = FastAPI()\n")
    info = webapps.detect(fastapi_app, "pkg/main.py")
    check(info["kind"] == "fastapi", "FastAPI определяется")
    check(info["module"] == "pkg.main", "путь с папкой превращается в pkg.main")

    uvicorn_self = write(
        folder,
        "u.py",
        "from fastapi import FastAPI\nimport uvicorn\napp = FastAPI()\nuvicorn.run(app)\n",
    )
    check(webapps.detect(uvicorn_self, "u.py")["self_start"] is True, "uvicorn.run() — самостоятельный запуск")

    mention = write(
        folder,
        "mention.py",
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "# запускать через app.run() не нужно\n"
        "MSG = 'подсказка: app.run() вызывать не надо'\n",
    )
    info = webapps.detect(mention, "mention.py")
    check(
        info["self_start"] is False,
        "app.run() в комментарии и в строке не считается запуском сервера",
    )

    script = write(folder, "hello.py", "print('привет')\n")
    info = webapps.detect(script, "hello.py")
    check(info["kind"] == "script", "обычный скрипт остаётся скриптом")
    check(info["self_start"] is False, "у обычного скрипта нет признаков сервера")


def test_command(folder: Path) -> None:
    print("Выбор команды запуска:")
    env = dict(os.environ)

    fastapi_app = folder / "pkg" / "main.py"
    command, mode, _ = webapps._command(fastapi_app, "pkg/main.py", 8300, env, folder)
    if mode == "uvicorn":
        check("boot" in " ".join(command), "FastAPI поднимается через загрузчик")
        check("8300" in command and "api" in command, "порт и имя приложения переданы")
        check("fastapi" in command, "режим fastapi передан загрузчику")
    else:
        check(mode == "python", "uvicorn не установлен — остаётся обычный запуск (без падения)")

    flask_app = folder / "site.py"
    command, mode, _ = webapps._command(flask_app, "site.py", 8301, env, folder)
    check(mode == "flask", "Flask без app.run() поднимается в режиме сервера")
    check("boot" in " ".join(command), "используется загрузчик по пути к файлу")
    check("8301" in command and "flask" in command, "порт и режим переданы загрузчику")

    self_run = folder / "self_run.py"
    _, mode, _ = webapps._command(self_run, "self_run.py", 8302, env, folder)
    check(mode == "python", "файл с srv.run() запускается как есть, без подмены")

    script = folder / "hello.py"
    command, mode, _ = webapps._command(script, "hello.py", 8303, env, folder)
    check(mode == "python" and str(script) in command, "обычный скрипт запускается напрямую")


def test_keepalive() -> None:
    print("Самопинг:")
    status = keepalive.status()
    for key in ("enabled", "url", "interval", "source", "reason"):
        check(key in status, f"в состоянии есть поле {key}")

    check(keepalive._is_local("http://127.0.0.1:8000") is True, "локальный адрес распознан")
    check(keepalive._is_local("http://localhost:5000/x") is True, "localhost распознан")
    check(keepalive._is_local("https://pyspace.onrender.com") is False, "внешний адрес не локальный")

    keepalive.remember_url("https://demo.onrender.com/login", source="запрос")
    remembered = keepalive.status()
    check(
        remembered["url"].startswith("https://demo.onrender.com"),
        "адрес выучен из входящего запроса",
    )
    check(remembered["source"] == "запрос", "источник адреса записан")

    keepalive.remember_url("http://127.0.0.1:8099/", source="запрос")
    check(
        keepalive.status()["url"].startswith("https://demo.onrender.com"),
        "локальный адрес не затирает внешний",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        test_detect(folder)
        test_command(folder)
        test_keepalive()
    print("\nВсе проверки автозапуска и самопинга пройдены ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
