"""Импорт и экспорт ZIP-архивов с защитой от zip-slip и zip-бомб."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from .config import settings
from .errors import AppError
from .paths import HIDDEN_NAMES, is_hidden, project_root

MAX_ENTRIES = 20000
MAX_UNCOMPRESSED_RATIO = 200


def _safe_segments(name: str) -> list[str] | None:
    cleaned = name.replace("\\", "/")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if any(part in HIDDEN_NAMES for part in parts):
        return None
    if Path(cleaned).is_absolute() or re.match(r"^[A-Za-z]:", cleaned):
        return None
    return parts


def _common_prefix(names: list[str]) -> str:
    """GitHub-архивы завёрнуты в одну папку — разворачиваем её."""
    tops = {name.split("/")[0] for name in names if name}
    if len(tops) != 1:
        return ""
    top = tops.pop()
    if all(name == top or name.startswith(f"{top}/") for name in names):
        return top
    return ""


def extract_zip(archive: Path | io.BytesIO, destination: Path, *, strip_root: bool = True) -> list[str]:
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []

    try:
        with zipfile.ZipFile(archive, "r") as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                raise AppError(f"В архиве больше {MAX_ENTRIES} элементов.", 413)

            total_uncompressed = sum(info.file_size for info in infos)
            total_compressed = max(sum(info.compress_size for info in infos), 1)
            if total_uncompressed / total_compressed > MAX_UNCOMPRESSED_RATIO:
                raise AppError("Архив выглядит как zip-бомба и не был распакован.", 413)
            if total_uncompressed > settings.max_upload_mb * 1024 * 1024 * 4:
                raise AppError("Распакованный размер превышает лимит.", 413)

            names = [info.filename.replace("\\", "/").rstrip("/") for info in infos]
            prefix = _common_prefix(names) if strip_root else ""

            for info in infos:
                segments = _safe_segments(info.filename)
                if not segments:
                    continue
                if prefix and segments[0] == prefix:
                    segments = segments[1:]
                    if not segments:
                        continue
                target = destination.joinpath(*segments).resolve()
                if target != destination and destination not in target.parents:
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, open(target, "wb") as sink:
                    while chunk := source.read(1024 * 256):
                        sink.write(chunk)
                extracted.append("/".join(segments))
    except zipfile.BadZipFile as exc:
        raise AppError("Файл повреждён или это не ZIP-архив.") from exc

    if not extracted:
        raise AppError("В архиве не нашлось подходящих файлов.")
    return extracted


def project_zip(project_id: int) -> io.BytesIO:
    base = project_root(project_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(base.rglob("*")):
            if not path.is_file() or is_hidden(path, base):
                continue
            zf.write(path, path.relative_to(base).as_posix())
    buffer.seek(0)
    return buffer


def folder_zip(folder: Path, arc_root: str = "") -> io.BytesIO:
    folder = Path(folder)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(folder).as_posix()
            zf.write(path, f"{arc_root}/{relative}" if arc_root else relative)
    buffer.seek(0)
    return buffer


def project_name_from_filename(filename: str) -> str:
    stem = Path(filename or "").stem or "Импорт"
    cleaned = re.sub(r"[^\wА-Яа-яЁё .\-]+", " ", stem).strip(" ._-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or "Импорт"
