"""WebSocket-канал терминала: браузер <-> PTY внутри проекта."""

from __future__ import annotations

import json

from flask import Flask
from flask_sock import Sock

from .auth import project_access
from .config import settings
from .errors import AppError
from .shell import PtySession, TerminalSpec

sock = Sock()

IDLE_TICK = 0.03          # как часто опрашиваем PTY, сек
MAX_INPUT_CHARS = 20000   # защита от гигантской вставки


def _send(ws, kind: str, **payload) -> None:
    ws.send(json.dumps({"type": kind, **payload}, ensure_ascii=False))


def register_sockets(app: Flask) -> None:
    sock.init_app(app)

    @sock.route("/ws/terminal/<int:project_id>")
    def terminal(ws, project_id: int):  # noqa: C901 - один цельный цикл обмена
        try:
            project_access(project_id, write=True)
            if not settings.enable_pty:
                raise AppError("Терминал отключён администратором.", 403)
        except AppError as exc:
            _send(ws, "error", message=exc.message, fatal=True)
            return

        session: PtySession | None = None
        try:
            handshake = ws.receive(timeout=10)
            spec = TerminalSpec(project_id=project_id)
            if handshake:
                try:
                    data = json.loads(handshake)
                    spec.cols = int(data.get("cols") or spec.cols)
                    spec.rows = int(data.get("rows") or spec.rows)
                    spec.cwd = str(data.get("cwd") or "")
                except (ValueError, TypeError):
                    pass

            session = PtySession(spec)
            _send(ws, "ready", **session.info())

            while True:
                chunk = session.read(IDLE_TICK)
                if chunk is None:
                    _send(ws, "exit", code=session.exit_code)
                    return
                if chunk:
                    _send(ws, "output", data=chunk)

                message = ws.receive(timeout=0)
                if message is None:
                    continue
                if not isinstance(message, str):
                    continue

                try:
                    event = json.loads(message)
                except ValueError:
                    session.write(message[:MAX_INPUT_CHARS])
                    continue

                kind = str(event.get("type", "input"))
                if kind == "input":
                    session.write(str(event.get("data", ""))[:MAX_INPUT_CHARS])
                elif kind == "resize":
                    session.resize(event.get("cols", 80), event.get("rows", 24))
                elif kind == "signal":
                    session.signal(str(event.get("name", "SIGINT")))
                elif kind == "ping":
                    _send(ws, "pong")
                elif kind == "close":
                    return
        except AppError as exc:
            _send(ws, "error", message=exc.message, fatal=True)
        except Exception as exc:  # noqa: BLE001 - соединение могло просто оборваться
            app.logger.info("Терминал закрыт: %s", exc)
        finally:
            if session is not None:
                session.close()
