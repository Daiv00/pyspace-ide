"""Единая точка конфигурации PySpace IDE.

Все настройки читаются из переменных окружения, поэтому один и тот же образ
работает и локально, и на Render без правок кода.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _resolve_data_dir() -> Path:
    """Куда писать БД и файлы пользователей.

    Приоритет:
      1. PYSPACE_DATA_DIR — явное указание (Render Persistent Disk -> /data);
      2. /data, если каталог существует и доступен для записи (диск подключён);
      3. <корень проекта>/var — локальная разработка и Render без диска.
    """
    explicit = os.getenv("PYSPACE_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    mounted = Path("/data")
    if mounted.is_dir() and os.access(mounted, os.W_OK):
        return mounted.resolve()

    return (PROJECT_ROOT / "var").resolve()


@dataclass(frozen=True)
class Settings:
    # --- окружение ---
    env: str = field(default_factory=lambda: os.getenv("PYSPACE_ENV", "production"))
    port: int = field(default_factory=lambda: _int("PORT", 8080))
    host: str = field(default_factory=lambda: os.getenv("PYSPACE_HOST", "0.0.0.0"))

    # --- секреты и сессии ---
    secret_key: str = field(
        default_factory=lambda: os.getenv("PYSPACE_SECRET") or secrets.token_hex(32)
    )
    secret_from_env: bool = field(default_factory=lambda: bool(os.getenv("PYSPACE_SECRET")))
    session_days: int = field(default_factory=lambda: _int("PYSPACE_SESSION_DAYS", 30))

    # --- каталоги ---
    data_dir: Path = field(default_factory=_resolve_data_dir)

    # --- лимиты ---
    max_upload_mb: int = field(default_factory=lambda: _int("PYSPACE_MAX_UPLOAD_MB", 200))
    max_file_kb: int = field(default_factory=lambda: _int("PYSPACE_MAX_FILE_KB", 4096))
    run_timeout: int = field(default_factory=lambda: _int("PYSPACE_RUN_TIMEOUT", 20))
    pip_timeout: int = field(default_factory=lambda: _int("PYSPACE_PIP_TIMEOUT", 180))
    stdin_limit: int = field(default_factory=lambda: _int("PYSPACE_STDIN_LIMIT", 40000))
    output_limit: int = field(default_factory=lambda: _int("PYSPACE_OUTPUT_LIMIT", 200000))

    # --- возможности ---
    enable_pty: bool = field(default_factory=lambda: _flag("PYSPACE_ENABLE_PTY", True))
    enable_registration: bool = field(
        default_factory=lambda: _flag("PYSPACE_ENABLE_REGISTRATION", True)
    )
    enable_preview: bool = field(default_factory=lambda: _flag("PYSPACE_ENABLE_PREVIEW", True))
    shell: str = field(default_factory=lambda: os.getenv("PYSPACE_SHELL", "/bin/bash"))

    # --- первый администратор ---
    admin_user: str = field(default_factory=lambda: os.getenv("PYSPACE_ADMIN_USER", "").strip())
    admin_password: str = field(default_factory=lambda: os.getenv("PYSPACE_ADMIN_PASSWORD", ""))

    @property
    def db_path(self) -> Path:
        explicit = os.getenv("PYSPACE_DB", "").strip()
        return Path(explicit).resolve() if explicit else self.data_dir / "pyspace.db"

    @property
    def storage_dir(self) -> Path:
        explicit = os.getenv("PYSPACE_STORAGE_DIR", "").strip()
        return Path(explicit).resolve() if explicit else self.data_dir / "projects"

    @property
    def drops_dir(self) -> Path:
        explicit = os.getenv("PYSPACE_DROPS_DIR", "").strip()
        return Path(explicit).resolve() if explicit else self.data_dir / "drops"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in {"dev", "development", "local"}

    @property
    def persistent(self) -> bool:
        """True, если данные лежат на подключённом диске, а не в контейнере."""
        return str(self.data_dir).startswith("/data")

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.storage_dir, self.drops_dir, self.tmp_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
