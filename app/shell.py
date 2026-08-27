"""Полноценный терминал: настоящий PTY внутри папки проекта.

Один PTY = одна WebSocket-сессия. Процесс запускается в своей сессии
(`setsid`), поэтому его вместе с потомками можно гарантированно закрыть.
"""

from __future__ import annotations

import fcntl
import os
import select
import shutil
import signal
import struct
import termios
from dataclasses import dataclass
from typing import Any

from .config import settings
from .errors import AppError
from .paths import project_root
from .runner import build_env

READ_CHUNK = 65536
MAX_COLS, MAX_ROWS = 500, 200

PROMPT = (
    r"\[\e[38;5;141m\]pyspace\[\e[0m\]:"
    r"\[\e[38;5;110m\]\w\[\e[0m\]"
    r"\[\e[38;5;141m\]\$\[\e[0m\] "
)

BANNER = (
    "\x1b[38;5;141mPySpace terminal\x1b[0m — оболочка запущена в папке проекта.\r\n"
    "python, pip, ls, git, curl и всё, что установлено в образе. "
    "Пакеты ставятся в ./.packages.\r\n\r\n"
)


def pick_shell() -> str:
    for candidate in (settings.shell, "/bin/bash", "/bin/sh"):
        if candidate and (os.path.isfile(candidate) or shutil.which(candidate)):
            return candidate
    raise AppError("В образе нет доступной оболочки.", 500)


@dataclass
class TerminalSpec:
    project_id: int
    cols: int = 100
    rows: int = 28
    cwd: str = ""


class PtySession:
    """Обёртка над pty + дочерним процессом оболочки."""

    def __init__(self, spec: TerminalSpec) -> None:
        if not settings.enable_pty:
            raise AppError("Терминал отключён администратором.", 403)
        if os.name != "posix":
            raise AppError("PTY-терминал доступен только в Linux/macOS окружении.", 501)

        import pty  # локальный импорт: модуля нет на Windows

        self.spec = spec
        root = project_root(spec.project_id)
        workdir = root
        if spec.cwd:
            candidate = (root / spec.cwd).resolve()
            if candidate.is_dir() and (candidate == root or root in candidate.parents):
                workdir = candidate

        shell_path = pick_shell()
        env = build_env(spec.project_id, {
            "PS1": PROMPT,
            "HISTFILE": str(root / ".pyspace_history"),
            "HISTSIZE": "2000",
            "PAGER": "cat",
            "GIT_PAGER": "cat",
            "COLUMNS": str(spec.cols),
            "LINES": str(spec.rows),
        })

        self.master_fd, slave_fd = pty.openpty()
        self._set_size(spec.cols, spec.rows)

        argv = [shell_path, "-i"] if shell_path.endswith("bash") else [shell_path]
        try:
            import subprocess

            self.process = subprocess.Popen(
                argv,
                preexec_fn=os.setsid,  # noqa: PLW1509 - нужна отдельная сессия для kill
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=str(workdir),
                env=env,
                close_fds=True,
            )
        finally:
            os.close(slave_fd)

        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.closed = False

    # ------------------------------------------------------------------ размер
    def _set_size(self, cols: int, rows: int) -> None:
        cols = max(20, min(int(cols or 80), MAX_COLS))
        rows = max(5, min(int(rows or 24), MAX_ROWS))
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, packed)

    def resize(self, cols: int, rows: int) -> None:
        if self.closed:
            return
        self._set_size(cols, rows)
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGWINCH)
        except OSError:
            pass

    # -------------------------------------------------------------------- ввод
    def write(self, data: str) -> None:
        if self.closed or not data:
            return
        payload = data.encode("utf-8", errors="replace")
        while payload:
            try:
                written = os.write(self.master_fd, payload)
                payload = payload[written:]
            except BlockingIOError:
                select.select([], [self.master_fd], [], 0.1)
            except OSError:
                self.close()
                return

    def signal(self, name: str) -> None:
        mapping = {"SIGINT": signal.SIGINT, "SIGTERM": signal.SIGTERM, "SIGKILL": signal.SIGKILL}
        target = mapping.get(name.upper())
        if not target or self.closed:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), target)
        except OSError:
            pass

    # ------------------------------------------------------------------- вывод
    def read(self, timeout: float = 0.05) -> str | None:
        """Возвращает данные, "" если пока тихо, None если PTY закрылся."""
        if self.closed:
            return None
        try:
            readable, _, _ = select.select([self.master_fd], [], [], timeout)
        except (OSError, ValueError):
            return None
        if not readable:
            return "" if self.alive else None
        try:
            chunk = os.read(self.master_fd, READ_CHUNK)
        except BlockingIOError:
            return ""
        except OSError:
            return None
        if not chunk:
            return None
        return chunk.decode("utf-8", errors="replace")

    @property
    def alive(self) -> bool:
        return (not self.closed) and self.process.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self.process.poll()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGHUP)
        except OSError:
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            except OSError:
                pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass

    def info(self) -> dict[str, Any]:
        return {
            "pid": self.process.pid,
            "project_id": self.spec.project_id,
            "cols": self.spec.cols,
            "rows": self.spec.rows,
        }
