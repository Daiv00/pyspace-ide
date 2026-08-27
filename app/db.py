"""Слой доступа к SQLite: соединение на запрос + версионные миграции."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Sequence

from flask import g

from .config import settings

# Каждая миграция применяется один раз; номер = PRAGMA user_version.
MIGRATIONS: list[str] = [
    # 1 — базовые таблицы
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT    NOT NULL UNIQUE,
        password_hash TEXT    NOT NULL,
        role          TEXT    NOT NULL DEFAULT 'user',
        created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
        last_seen_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS projects (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name          TEXT    NOT NULL,
        preview_token TEXT    NOT NULL UNIQUE,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);

    CREATE TABLE IF NOT EXISTS members (
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
        role       TEXT    NOT NULL DEFAULT 'editor',
        created_at TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (project_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS drops (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token      TEXT    NOT NULL UNIQUE,
        label      TEXT    NOT NULL DEFAULT '',
        active     INTEGER NOT NULL DEFAULT 1,
        created_at TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_drops_owner ON drops(owner_id);

    CREATE TABLE IF NOT EXISTS received_files (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        drop_token    TEXT    NOT NULL,
        owner_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        recipient_id  INTEGER          REFERENCES users(id) ON DELETE SET NULL,
        stored_path   TEXT    NOT NULL,
        original_name TEXT    NOT NULL,
        size          INTEGER NOT NULL DEFAULT 0,
        kind          TEXT    NOT NULL DEFAULT 'file',
        created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_received_recipient ON received_files(recipient_id);
    CREATE INDEX IF NOT EXISTS idx_received_token     ON received_files(drop_token);
    """,
]


def connect() -> sqlite3.Connection:
    """Новое соединение вне контекста запроса (миграции, CLI, тесты)."""
    conn = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def get_db() -> sqlite3.Connection:
    """Соединение, живущее ровно один HTTP-запрос."""
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def query_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def execute(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    return get_db().execute(sql, params)


def execute_many(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    get_db().executemany(sql, seq)


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def migrate() -> int:
    """Догоняет схему до последней версии. Идемпотентно."""
    settings.ensure_dirs()
    conn = connect()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for index, script in enumerate(MIGRATIONS, start=1):
            if index <= version:
                continue
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {index}")
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
