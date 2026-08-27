"""Безопасная работа с путями внутри песочницы проекта.

Единственное место в коде, которое превращает пользовательский ввод в путь на
диске. Любая попытка выйти за корень проекта заканчивается AppError.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import settings
from .errors import AppError

MAX_PATH_LEN = 400
MAX_SEGMENT_LEN = 120

# Символы, ломающие файловые системы Windows/Linux. Юникод (в т.ч. кириллица) сохраняем.
_UNSAFE = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED_WINDOWS = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

# Каталоги и файлы, которые IDE прячет от пользователя и не кладёт в архивы.
HIDDEN_NAMES = {"__pycache__", ".git", ".packages", ".venv", "node_modules", ".pyspace"}
HIDDEN_SUFFIXES = {".pyc", ".pyo"}


def normalize_relpath(raw: str | None, *, allow_empty: bool = False) -> str:
    """Приводит путь к виду `a/b/c.py`, отбрасывая всё опасное."""
    text = str(raw or "").replace("\\", "/").strip()
    if len(text) > MAX_PATH_LEN:
        raise AppError("Слишком длинный путь.")

    segments: list[str] = []
    for part in text.split("/"):
        part = unicodedata.normalize("NFC", part).strip()
        if part in ("", "."):
            continue
        if part == "..":
            raise AppError("Переход выше корня проекта запрещён.")
        part = _UNSAFE.sub("_", part).rstrip(". ")
        if not part:
            continue
        if part.split(".")[0].lower() in _RESERVED_WINDOWS:
            part = f"_{part}"
        if len(part) > MAX_SEGMENT_LEN:
            stem, dot, suffix = part.rpartition(".")
            part = (stem[: MAX_SEGMENT_LEN - len(suffix) - 1] + dot + suffix) if dot else part[:MAX_SEGMENT_LEN]
        segments.append(part)

    if not segments:
        if allow_empty:
            return ""
        raise AppError("Укажите имя файла или папки.")
    return "/".join(segments)


def project_root(project_id: int) -> Path:
    root = settings.storage_dir / f"project_{int(project_id)}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def packages_dir(project_id: int) -> Path:
    path = project_root(project_id) / ".packages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def drop_root(token: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", token or ""):
        raise AppError("Некорректный токен обмена.", 404)
    path = settings.drops_dir / f"drop_{token}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_inside(base: Path, relative: str, *, allow_empty: bool = False) -> Path:
    """Абсолютный путь внутри `base` или ошибка."""
    normalized = normalize_relpath(relative, allow_empty=allow_empty)
    base = base.resolve()
    target = (base / normalized).resolve() if normalized else base
    if target != base and base not in target.parents:
        raise AppError("Путь вне рабочей папки проекта.", 403)
    return target


def project_path(project_id: int, relative: str, *, allow_empty: bool = False) -> Path:
    return resolve_inside(project_root(project_id), relative, allow_empty=allow_empty)


def drop_path(token: str, relative: str) -> Path:
    return resolve_inside(drop_root(token), relative)


def is_hidden(path: Path, base: Path) -> bool:
    """Служебные файлы не показываем в дереве и не архивируем."""
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        return True
    if any(part in HIDDEN_NAMES for part in parts):
        return True
    return path.suffix.lower() in HIDDEN_SUFFIXES


def unique_path(target: Path) -> Path:
    """`main.py` -> `main (2).py`, если файл уже существует."""
    if not target.exists():
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise AppError("Не удалось подобрать свободное имя файла.")


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
