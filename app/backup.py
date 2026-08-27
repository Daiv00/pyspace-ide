"""Автобэкап данных в приватный репозиторий GitHub.

Зачем: на бесплатном плане Render нет постоянного диска, и при каждом деплое или
перезапуске база с файлами проектов исчезает. Этот модуль складывает всё в один
`tar.gz` и заливает его в приватный репозиторий через GitHub API, а при старте
пустого контейнера — скачивает обратно. Из бесплатных вариантов это самый простой:
один токен, никаких OAuth-приложений и сервисных аккаунтов, как у Google Drive.

Что нужно задать в переменных окружения:
    PYSPACE_BACKUP_REPO   = логин/репозиторий   (приватный репозиторий для копий)
    PYSPACE_BACKUP_TOKEN  = fine-grained PAT с правом Contents: Read and write

Необязательно:
    PYSPACE_BACKUP_BRANCH   ветка (по умолчанию main)
    PYSPACE_BACKUP_PATH     путь файла в репозитории (по умолчанию backups/pyspace-data.tar.gz)
    PYSPACE_BACKUP_INTERVAL период автосохранения в секундах (по умолчанию 900)
    PYSPACE_BACKUP_MAX_MB   предохранитель по размеру архива (по умолчанию 40)
    PYSPACE_BACKUP_RESTORE  0 — не восстанавливать автоматически при старте
"""

from __future__ import annotations

import atexit
import base64
import datetime as dt
import hashlib
import io
import logging
import os
import tarfile
import threading
import time

import requests

from .config import settings

log = logging.getLogger("pyspace.backup")

API = "https://api.github.com"
# Каталоги, которые не имеет смысла таскать в копии.
SKIP_DIRS = {"__pycache__", ".packages", "node_modules", ".venv", "venv", ".git", "tmp"}

_state: dict[str, object] = {
    "configured": False,
    "repo": None,
    "path": None,
    "interval": 0,
    "auto_restore": True,
    "last_backup_at": None,
    "last_backup_size": None,
    "last_restore_at": None,
    "last_error": None,
    "backups": 0,
}
_lock = threading.Lock()
_thread: threading.Thread | None = None
_fingerprint: str | None = None


# --------------------------------------------------------------------------- #
# состояние
# --------------------------------------------------------------------------- #

def configured() -> bool:
    return bool(settings.backup_repo and settings.backup_token)


def status() -> dict:
    with _lock:
        snapshot = dict(_state)
    snapshot.update(
        {
            "configured": configured(),
            "repo": settings.backup_repo or None,
            "path": settings.backup_path,
            "interval": settings.backup_interval,
            "auto_restore": settings.backup_restore,
        }
    )
    return snapshot


def _remember(**values) -> None:
    with _lock:
        _state.update(values)


# --------------------------------------------------------------------------- #
# архив
# --------------------------------------------------------------------------- #

def _sources() -> list[tuple[str, str]]:
    """Пары (путь на диске, имя внутри архива)."""
    items: list[tuple[str, str]] = []
    if settings.db_path.exists():
        items.append((str(settings.db_path), "pyspace.db"))
    if settings.storage_dir.is_dir():
        items.append((str(settings.storage_dir), "projects"))
    return items


def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = set(info.name.split("/"))
    if parts & SKIP_DIRS:
        return None
    if not (info.isfile() or info.isdir()):
        return None  # симлинки и устройства в копию не берём
    info.uid = info.gid = 0
    info.uname = info.gname = "pyspace"
    return info


def build_archive() -> bytes:
    """Собрать tar.gz со всеми данными в памяти."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for source, name in _sources():
            archive.add(source, arcname=name, filter=_filter)
    return buffer.getvalue()


def fingerprint() -> str:
    """Отпечаток данных: если не менялись — не гоняем сеть впустую."""
    digest = hashlib.sha256()
    for source, name in _sources():
        if os.path.isfile(source):
            stat = os.stat(source)
            digest.update(f"{name}:{stat.st_size}:{int(stat.st_mtime)}|".encode())
            continue
        for root, dirs, files in os.walk(source):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for filename in sorted(files):
                try:
                    stat = os.stat(os.path.join(root, filename))
                except OSError:
                    continue
                rel = os.path.relpath(os.path.join(root, filename), source)
                digest.update(f"{name}/{rel}:{stat.st_size}:{int(stat.st_mtime)}|".encode())
    return digest.hexdigest()


def extract_archive(blob: bytes) -> int:
    """Распаковать копию в каталог данных. Возвращает число файлов."""
    root = settings.data_dir.resolve()
    restored = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not (member.isfile() or member.isdir()):
                continue
            target = (root / member.name).resolve()
            if not str(target).startswith(str(root)):  # защита от путей вида ../
                log.warning("Пропущен подозрительный путь в архиве: %s", member.name)
                continue
            archive.extract(member, path=root, set_attrs=False)
            if member.isfile():
                restored += 1
    # имя внутри архива — pyspace.db, а настройки могут указывать другой путь
    default_db = root / "pyspace.db"
    if default_db.exists() and settings.db_path != default_db:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        default_db.replace(settings.db_path)
    return restored


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #

def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.backup_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pyspace-backup/1.0",
    }


def _meta() -> dict | None:
    """Метаданные существующей копии в репозитории (или None)."""
    url = f"{API}/repos/{settings.backup_repo}/contents/{settings.backup_path}"
    response = requests.get(
        url,
        headers=_headers(),
        params={"ref": settings.backup_branch},
        timeout=60,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def upload(blob: bytes) -> dict:
    """Залить копию, перезаписав предыдущую."""
    limit = settings.backup_max_mb * 1024 * 1024
    if len(blob) > limit:
        raise RuntimeError(
            f"Архив {len(blob) // 1024 // 1024} МБ больше лимита "
            f"{settings.backup_max_mb} МБ. Увеличьте PYSPACE_BACKUP_MAX_MB "
            f"или уберите лишние файлы из проектов."
        )

    existing = _meta()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = {
        "message": f"Копия данных PySpace IDE · {stamp}",
        "content": base64.b64encode(blob).decode("ascii"),
        "branch": settings.backup_branch,
    }
    if existing and existing.get("sha"):
        body["sha"] = existing["sha"]

    url = f"{API}/repos/{settings.backup_repo}/contents/{settings.backup_path}"
    response = requests.put(url, headers=_headers(), json=body, timeout=180)
    if response.status_code >= 400:
        raise RuntimeError(f"GitHub ответил {response.status_code}: {response.text[:200]}")
    return response.json()


def download() -> bytes | None:
    """Скачать последнюю копию (или None, если её нет)."""
    existing = _meta()
    if not existing or not existing.get("sha"):
        return None
    url = f"{API}/repos/{settings.backup_repo}/git/blobs/{existing['sha']}"
    headers = _headers() | {"Accept": "application/vnd.github.raw"}
    response = requests.get(url, headers=headers, timeout=180)
    response.raise_for_status()
    return response.content


# --------------------------------------------------------------------------- #
# операции
# --------------------------------------------------------------------------- #

def backup_now(force: bool = True) -> dict:
    """Сделать копию сейчас. force=False — только если данные менялись."""
    global _fingerprint

    if not configured():
        raise RuntimeError(
            "Бэкап не настроен: задайте PYSPACE_BACKUP_REPO и PYSPACE_BACKUP_TOKEN."
        )

    current = fingerprint()
    if not force and current == _fingerprint:
        return {"skipped": True, "reason": "данные не менялись"}

    blob = build_archive()
    try:
        upload(blob)
    except Exception as error:
        _remember(last_error=str(error)[:300])
        raise

    _fingerprint = current
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with _lock:
        _state.update(
            {
                "last_backup_at": now,
                "last_backup_size": len(blob),
                "last_error": None,
                "backups": int(_state["backups"] or 0) + 1,
            }
        )
    log.info("Копия залита: %s КБ", len(blob) // 1024)
    return {"skipped": False, "size": len(blob), "at": now}


def restore_now() -> dict:
    """Восстановить данные из последней копии."""
    if not configured():
        raise RuntimeError(
            "Бэкап не настроен: задайте PYSPACE_BACKUP_REPO и PYSPACE_BACKUP_TOKEN."
        )
    blob = download()
    if blob is None:
        return {"restored": 0, "found": False}
    files = extract_archive(blob)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _remember(last_restore_at=now, last_error=None)
    log.info("Данные восстановлены из копии: %s файлов", files)
    return {"restored": files, "found": True, "at": now}


def restore_on_start() -> None:
    """Поднять данные из копии, если контейнер стартовал пустым.

    Вызывается ДО миграций: если базы нет, значит диск чистый (первый запуск
    после деплоя на плане без постоянного диска) — пробуем скачать копию.
    """
    if not configured() or not settings.backup_restore:
        return
    if settings.db_path.exists():
        return
    try:
        result = restore_now()
        if not result.get("found"):
            log.info("Копии в репозитории пока нет — начинаем с чистой базы.")
    except Exception as error:
        _remember(last_error=str(error)[:300])
        log.warning("Не удалось восстановить данные из копии: %s", error)


def start(app) -> None:
    """Периодическое автосохранение + попытка сохранить при остановке."""
    global _thread, _fingerprint

    if not configured():
        app.logger.info(
            "Автобэкап выключен: не заданы PYSPACE_BACKUP_REPO / PYSPACE_BACKUP_TOKEN."
        )
        return
    if _thread and _thread.is_alive():
        return

    _fingerprint = fingerprint()
    interval = max(300, settings.backup_interval)

    def loop() -> None:
        time.sleep(60)
        while True:
            try:
                backup_now(force=False)
            except Exception as error:
                log.warning("Автобэкап не удался: %s", error)
            time.sleep(interval)

    _thread = threading.Thread(target=loop, name="pyspace-backup", daemon=True)
    _thread.start()

    def on_exit() -> None:  # редеплой и перезапуск — последний шанс сохранить
        try:
            backup_now(force=False)
        except Exception:
            pass

    atexit.register(on_exit)
    app.logger.info(
        "Автобэкап включён: %s (%s) каждые %s с",
        settings.backup_repo,
        settings.backup_path,
        interval,
    )
