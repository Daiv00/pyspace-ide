"""Чтение и изменение дерева файлов проекта."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .config import settings
from .errors import AppError
from .languages import is_binary_name, language_for
from .paths import (
    is_hidden,
    normalize_relpath,
    project_path,
    project_root,
    unique_path,
)

MAX_TREE_ENTRIES = 4000


def _node(path: Path, base: Path) -> dict[str, Any]:
    relative = path.relative_to(base).as_posix()
    if path.is_dir():
        return {"path": relative, "name": path.name, "type": "dir"}
    stat = path.stat()
    return {
        "path": relative,
        "name": path.name,
        "type": "file",
        "size": stat.st_size,
        "modified": int(stat.st_mtime),
        "language": language_for(path.name),
        "binary": is_binary_name(path.name),
    }


def list_tree(project_id: int) -> list[dict[str, Any]]:
    """Плоский список узлов; дерево собирает фронтенд."""
    base = project_root(project_id)
    nodes: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*"), key=lambda p: p.as_posix().lower()):
        if is_hidden(path, base):
            continue
        nodes.append(_node(path, base))
        if len(nodes) >= MAX_TREE_ENTRIES:
            break
    nodes.sort(key=lambda n: (n["path"].count("/"), n["type"] != "dir", n["name"].lower()))
    return nodes


def read_file(project_id: int, relative: str) -> dict[str, Any]:
    path = project_path(project_id, relative)
    if not path.is_file():
        raise AppError("Файл не найден.", 404)

    limit = settings.max_file_kb * 1024
    size = path.stat().st_size
    if is_binary_name(path.name):
        return {
            "path": path.relative_to(project_root(project_id)).as_posix(),
            "content": "",
            "language": "plaintext",
            "binary": True,
            "size": size,
        }
    if size > limit:
        raise AppError(
            f"Файл больше {settings.max_file_kb} КБ — откройте его скачиванием.", 413
        )
    return {
        "path": path.relative_to(project_root(project_id)).as_posix(),
        "content": path.read_text(encoding="utf-8", errors="replace"),
        "language": language_for(path.name),
        "binary": False,
        "size": size,
    }


def write_file(project_id: int, relative: str, content: str) -> dict[str, Any]:
    path = project_path(project_id, relative)
    if path.is_dir():
        raise AppError("По этому пути находится папка.")
    payload = content.encode("utf-8")
    limit = settings.max_file_kb * 1024
    if len(payload) > limit:
        raise AppError(f"Файл больше лимита {settings.max_file_kb} КБ.", 413)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": path.relative_to(project_root(project_id)).as_posix(), "size": len(payload)}


def create_file(project_id: int, relative: str, content: str = "") -> dict[str, Any]:
    path = project_path(project_id, relative)
    if path.exists():
        raise AppError("Файл или папка с таким именем уже существует.", 409)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": path.relative_to(project_root(project_id)).as_posix()}


def create_dir(project_id: int, relative: str) -> dict[str, Any]:
    path = project_path(project_id, relative)
    if path.exists():
        raise AppError("Папка уже существует.", 409)
    path.mkdir(parents=True)
    return {"path": path.relative_to(project_root(project_id)).as_posix()}


def move(project_id: int, source: str, destination: str) -> dict[str, Any]:
    base = project_root(project_id)
    src = project_path(project_id, source)
    dst = project_path(project_id, destination)
    if not src.exists():
        raise AppError("Исходный файл не найден.", 404)
    if src == dst:
        return {"path": dst.relative_to(base).as_posix()}
    if dst.exists():
        raise AppError("По новому пути уже есть файл или папка.", 409)
    if src.is_dir() and src in dst.parents:
        raise AppError("Нельзя переместить папку внутрь себя самой.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"path": dst.relative_to(base).as_posix()}


def copy(project_id: int, source: str, destination: str) -> dict[str, Any]:
    base = project_root(project_id)
    src = project_path(project_id, source)
    dst = unique_path(project_path(project_id, destination))
    if not src.exists():
        raise AppError("Исходный файл не найден.", 404)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return {"path": dst.relative_to(base).as_posix()}


def delete(project_id: int, relative: str) -> dict[str, Any]:
    path = project_path(project_id, relative)
    if not path.exists():
        return {"path": normalize_relpath(relative), "deleted": False}
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {"path": normalize_relpath(relative), "deleted": True}


def save_uploads(project_id: int, files, target_dir: str = "") -> list[str]:
    """Сохраняет загруженные файлы, сохраняя относительные пути из браузера."""
    base = project_root(project_id)
    prefix = normalize_relpath(target_dir, allow_empty=True)
    saved: list[str] = []
    for item in files:
        raw_name = (item.filename or "").replace("\\", "/").strip("/")
        if not raw_name:
            continue
        relative = f"{prefix}/{raw_name}" if prefix else raw_name
        try:
            path = project_path(project_id, relative)
        except AppError:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        item.save(str(path))
        saved.append(path.relative_to(base).as_posix())
    if not saved:
        raise AppError("Не удалось сохранить ни один файл.")
    return saved


def scaffold(project_id: int, template: str = "python") -> None:
    """Стартовые файлы нового проекта."""
    if template == "web":
        create_file(
            project_id,
            "index.html",
            "<!doctype html>\n"
            '<html lang="ru">\n<head>\n  <meta charset="utf-8">\n'
            '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "  <title>Мой проект</title>\n"
            '  <link rel="stylesheet" href="style.css">\n'
            "</head>\n<body>\n  <h1>Привет, PySpace</h1>\n"
            '  <script src="script.js"></script>\n</body>\n</html>\n',
        )
        create_file(
            project_id,
            "style.css",
            "body {\n  margin: 0;\n  display: grid;\n  place-items: center;\n"
            "  min-height: 100vh;\n  font-family: system-ui, sans-serif;\n"
            "  background: #0f1117;\n  color: #f5f7fb;\n}\n",
        )
        create_file(
            project_id,
            "script.js",
            "document.querySelector('h1').addEventListener('click', () => {\n"
            "  console.log('Живой предпросмотр работает');\n});\n",
        )
        return

    if template == "sql":
        create_file(
            project_id,
            "schema.sql",
            "CREATE TABLE users (\n  id INTEGER PRIMARY KEY,\n  name TEXT NOT NULL\n);\n\n"
            "INSERT INTO users (name) VALUES ('Денис'), ('Гость');\n\n"
            "SELECT * FROM users;\n",
        )
        return

    if template == "empty":
        return

    create_file(
        project_id,
        "main.py",
        'def main() -> None:\n    name = input("Как вас зовут? ") or "мир"\n'
        '    print(f"Привет, {name}!")\n\n\n'
        'if __name__ == "__main__":\n    main()\n',
    )
    create_file(project_id, "requirements.txt", "# пакеты проекта, например:\n# requests\n")


MAX_SEARCH_HITS = 300
MAX_SEARCH_BYTES = 1_500_000


def search(
    project_id: int,
    query: str,
    case_sensitive: bool = False,
    limit: int = MAX_SEARCH_HITS,
) -> list[dict[str, Any]]:
    """Простой полнотекстовый поиск по текстовым файлам проекта."""
    query = (query or "").strip()
    if len(query) < 2:
        raise AppError("Запрос должен быть не короче двух символов.")

    base = project_root(project_id)
    needle = query if case_sensitive else query.lower()
    hits: list[dict[str, Any]] = []

    for path in sorted(base.rglob("*"), key=lambda p: p.as_posix().lower()):
        if len(hits) >= limit:
            break
        if not path.is_file() or is_hidden(path, base) or is_binary_name(path.name):
            continue
        try:
            if path.stat().st_size > MAX_SEARCH_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        relative = path.relative_to(base).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            haystack = line if case_sensitive else line.lower()
            column = haystack.find(needle)
            if column < 0:
                continue
            hits.append(
                {
                    "path": relative,
                    "line": number,
                    "column": column + 1,
                    "preview": line.strip()[:200],
                }
            )
            if len(hits) >= limit:
                break
    return hits
