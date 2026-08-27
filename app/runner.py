"""Запуск пользовательского кода: Python, SQL и установка пакетов."""

from __future__ import annotations

import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import settings
from .errors import AppError
from .languages import run_kind
from .paths import packages_dir, project_path, project_root

PACKAGE_SPEC_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}"          # имя
    r"(?:\[[A-Za-z0-9._,-]{1,120}\])?"            # extras
    r"(?:\s*(?:==|~=|>=|<=|!=|>|<)\s*[A-Za-z0-9._*+!-]{1,60})?$"  # версия
)


def build_env(project_id: int, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Окружение процесса проекта: локальные пакеты видны, HOME внутри проекта."""
    root = project_root(project_id)
    packages = packages_dir(project_id)
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(root),
        "TMPDIR": str(settings.tmp_dir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "xterm-256color",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(packages),
        "PYSPACE_PROJECT_ID": str(project_id),
        "PYSPACE_PROJECT_DIR": str(root),
        "PIP_TARGET": str(packages),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
    }
    if extra:
        env.update(extra)
    return env


def _clip(text: str) -> str:
    limit = settings.output_limit
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… вывод обрезан на {limit} символах."


def _spawn(argv: list[str], cwd: Path, env: dict[str, str], stdin_data: str, timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    kwargs: dict[str, Any] = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # чтобы убить всё дерево процессов

    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
    except FileNotFoundError as exc:
        raise AppError(f"Исполняемый файл не найден: {exc.filename}", 500) from exc

    timed_out = False
    try:
        output, _ = process.communicate(input=stdin_data, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process)
        output, _ = process.communicate()
        output = (output or "") + (
            f"\n⏱ Превышен лимит {timeout} с. Процесс остановлен "
            "(возможен бесконечный цикл или ожидание input())."
        )

    return {
        "ok": (not timed_out) and process.returncode == 0,
        "returncode": -1 if timed_out else process.returncode,
        "output": _clip(output or ""),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "timed_out": timed_out,
    }


def _kill_tree(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except Exception:  # noqa: BLE001 - процесс уже мёртв
            pass


def run_python(project_id: int, relative: str, stdin_data: str = "", args: list[str] | None = None) -> dict[str, Any]:
    script = project_path(project_id, relative)
    if not script.is_file():
        raise AppError("Файл не найден.", 404)
    if len(stdin_data) > settings.stdin_limit:
        raise AppError("Слишком много тестовых данных для stdin.", 413)

    root = project_root(project_id)
    argv = [sys.executable, "-u", str(script), *(args or [])]
    result = _spawn(argv, root, build_env(project_id), stdin_data, settings.run_timeout)
    result["kind"] = "python"
    return result


def run_sql(project_id: int, relative: str) -> dict[str, Any]:
    """Выполняет скрипт в отдельной SQLite-БД проекта и показывает результат."""
    script_path = project_path(project_id, relative)
    if not script_path.is_file():
        raise AppError("Файл не найден.", 404)

    script = script_path.read_text(encoding="utf-8", errors="replace")
    started = time.monotonic()
    lines: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pyspace_sql_", dir=settings.tmp_dir) as tmp:
        connection = sqlite3.connect(Path(tmp) / "scratch.sqlite3")
        connection.row_factory = sqlite3.Row
        try:
            cursor = connection.cursor()
            for statement in _split_sql(script):
                cursor.execute(statement)
                if cursor.description:
                    columns = [column[0] for column in cursor.description]
                    rows = cursor.fetchmany(200)
                    lines.append(_render_table(columns, rows))
                else:
                    lines.append(f"OK · затронуто строк: {max(cursor.rowcount, 0)}")
            connection.commit()
            ok, returncode = True, 0
        except sqlite3.Error as exc:
            lines.append(f"Ошибка SQL: {exc}")
            ok, returncode = False, 1
        finally:
            connection.close()

    return {
        "ok": ok,
        "kind": "sql",
        "returncode": returncode,
        "output": _clip("\n\n".join(lines) or "Скрипт не содержит выражений."),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "timed_out": False,
    }


def _split_sql(script: str) -> list[str]:
    statements, buffer, in_string, quote = [], [], False, ""
    index = 0
    while index < len(script):
        char = script[index]
        if in_string:
            buffer.append(char)
            if char == quote:
                in_string = False
        elif char in ("'", '"'):
            in_string, quote = True, char
            buffer.append(char)
        elif char == "-" and script[index : index + 2] == "--":
            while index < len(script) and script[index] != "\n":
                index += 1
            continue
        elif char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        else:
            buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _render_table(columns: list[str], rows: list[sqlite3.Row]) -> str:
    if not rows:
        return " | ".join(columns) + "\n(пусто)"
    table = [columns] + [[("NULL" if value is None else str(value)) for value in row] for row in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(columns))]
    separator = "-+-".join("-" * width for width in widths)
    lines = [" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(table[0])), separator]
    lines += [" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in table[1:]]
    lines.append(f"({len(rows)} строк)")
    return "\n".join(lines)


def run_file(project_id: int, relative: str, stdin_data: str = "") -> dict[str, Any]:
    kind = run_kind(relative)
    if kind == "python":
        return run_python(project_id, relative, stdin_data)
    if kind == "sql":
        return run_sql(project_id, relative)
    if kind in ("html", "css"):
        return {
            "ok": True,
            "kind": kind,
            "returncode": 0,
            "output": "Откройте вкладку «Просмотр» — файл рендерится в живом предпросмотре.",
            "duration_ms": 0,
            "timed_out": False,
        }
    raise AppError("Запуск поддерживается для .py и .sql; HTML/CSS открываются в предпросмотре.")


def pip_install(project_id: int, spec: str) -> dict[str, Any]:
    spec = (spec or "").strip()
    if not PACKAGE_SPEC_RE.fullmatch(spec):
        raise AppError("Неверный формат пакета. Пример: requests или requests==2.32.3")
    argv = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check", "--no-input", "--no-cache-dir",
        "--target", str(packages_dir(project_id)), "--upgrade", spec,
    ]
    result = _spawn(argv, project_root(project_id), build_env(project_id), "", settings.pip_timeout)
    result["kind"] = "pip"
    result["package"] = spec
    return result


def pip_list(project_id: int) -> dict[str, Any]:
    argv = [
        sys.executable, "-m", "pip", "list", "--path", str(packages_dir(project_id)),
        "--disable-pip-version-check", "--format", "json",
    ]
    result = _spawn(argv, project_root(project_id), build_env(project_id), "", 60)
    result["kind"] = "pip"
    return result
