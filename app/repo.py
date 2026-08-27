"""Репозитории: все SQL-запросы приложения собраны здесь."""

from __future__ import annotations

import secrets
import sqlite3
import string
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .errors import AppError

TOKEN_ALPHABET = string.ascii_letters + string.digits


def new_token(length: int = 8) -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


# --------------------------------------------------------------------------- users


class Users:
    @staticmethod
    def count() -> int:
        row = db.query_one("SELECT COUNT(*) AS n FROM users")
        return int(row["n"]) if row else 0

    @staticmethod
    def by_id(user_id: int) -> sqlite3.Row | None:
        return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))

    @staticmethod
    def by_name(username: str) -> sqlite3.Row | None:
        return db.query_one("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,))

    @staticmethod
    def create(username: str, password: str, role: str = "user") -> int:
        try:
            cursor = db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), role),
            )
        except sqlite3.IntegrityError as exc:
            raise AppError("Такой логин уже занят.", 409) from exc
        return int(cursor.lastrowid)

    @staticmethod
    def verify(username: str, password: str) -> sqlite3.Row | None:
        user = Users.by_name(username)
        if user and check_password_hash(user["password_hash"], password):
            return user
        return None

    @staticmethod
    def set_password(user_id: int, password: str) -> None:
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )

    @staticmethod
    def set_role(user_id: int, role: str) -> None:
        db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    @staticmethod
    def delete(user_id: int) -> None:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    @staticmethod
    def touch(user_id: int) -> None:
        db.execute("UPDATE users SET last_seen_at = datetime('now') WHERE id = ?", (user_id,))

    @staticmethod
    def all() -> list[dict[str, Any]]:
        rows = db.query(
            """
            SELECT u.id, u.username, u.role, u.created_at, u.last_seen_at,
                   (SELECT COUNT(*) FROM projects p WHERE p.owner_id = u.id) AS projects
            FROM users u ORDER BY u.id
            """
        )
        return db.rows_to_dicts(rows)

    @staticmethod
    def admin_count() -> int:
        row = db.query_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin'")
        return int(row["n"]) if row else 0


# ------------------------------------------------------------------------ projects


class Projects:
    @staticmethod
    def for_user(user_id: int) -> list[dict[str, Any]]:
        rows = db.query(
            """
            SELECT p.id, p.name, p.owner_id, p.created_at, p.updated_at, p.preview_token,
                   u.username AS owner_name,
                   CASE WHEN p.owner_id = ? THEN 'owner' ELSE m.role END AS access
            FROM projects p
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN members m ON m.project_id = p.id AND m.user_id = ?
            WHERE p.owner_id = ? OR m.user_id = ?
            ORDER BY p.updated_at DESC, p.id DESC
            """,
            (user_id, user_id, user_id, user_id),
        )
        return db.rows_to_dicts(rows)

    @staticmethod
    def access(project_id: int, user_id: int) -> dict[str, Any] | None:
        row = db.query_one(
            """
            SELECT p.*, CASE WHEN p.owner_id = ? THEN 'owner' ELSE m.role END AS access
            FROM projects p
            LEFT JOIN members m ON m.project_id = p.id AND m.user_id = ?
            WHERE p.id = ? AND (p.owner_id = ? OR m.user_id = ?)
            """,
            (user_id, user_id, project_id, user_id, user_id),
        )
        return dict(row) if row else None

    @staticmethod
    def by_preview_token(token: str) -> dict[str, Any] | None:
        row = db.query_one("SELECT * FROM projects WHERE preview_token = ?", (token,))
        return dict(row) if row else None

    @staticmethod
    def unique_name(owner_id: int, base: str) -> str:
        name, index = base, 2
        while db.query_one(
            "SELECT 1 FROM projects WHERE owner_id = ? AND name = ? COLLATE NOCASE",
            (owner_id, name),
        ):
            name = f"{base} ({index})"
            index += 1
        return name

    @staticmethod
    def create(owner_id: int, name: str) -> dict[str, Any]:
        name = Projects.unique_name(owner_id, name)
        token = new_token(12)
        cursor = db.execute(
            "INSERT INTO projects (owner_id, name, preview_token) VALUES (?, ?, ?)",
            (owner_id, name, token),
        )
        project_id = int(cursor.lastrowid)
        db.execute(
            "INSERT INTO members (project_id, user_id, role) VALUES (?, ?, 'owner')",
            (project_id, owner_id),
        )
        return {"id": project_id, "name": name, "preview_token": token, "access": "owner"}

    @staticmethod
    def rename(project_id: int, name: str) -> None:
        db.execute(
            "UPDATE projects SET name = ?, updated_at = datetime('now') WHERE id = ?",
            (name, project_id),
        )

    @staticmethod
    def touch(project_id: int) -> None:
        db.execute(
            "UPDATE projects SET updated_at = datetime('now') WHERE id = ?", (project_id,)
        )

    @staticmethod
    def delete(project_id: int) -> None:
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    @staticmethod
    def members(project_id: int) -> list[dict[str, Any]]:
        rows = db.query(
            """
            SELECT u.id, u.username, m.role, m.created_at
            FROM members m JOIN users u ON u.id = m.user_id
            WHERE m.project_id = ? ORDER BY m.role, u.username
            """,
            (project_id,),
        )
        return db.rows_to_dicts(rows)

    @staticmethod
    def add_member(project_id: int, user_id: int, role: str) -> None:
        db.execute(
            """
            INSERT INTO members (project_id, user_id, role) VALUES (?, ?, ?)
            ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role
            """,
            (project_id, user_id, role),
        )

    @staticmethod
    def remove_member(project_id: int, user_id: int) -> None:
        db.execute(
            "DELETE FROM members WHERE project_id = ? AND user_id = ? AND role <> 'owner'",
            (project_id, user_id),
        )


# --------------------------------------------------------------------------- drops


class Drops:
    @staticmethod
    def create(owner_id: int, label: str = "") -> dict[str, Any]:
        for _ in range(40):
            token = new_token(8)
            if not db.query_one("SELECT 1 FROM drops WHERE token = ?", (token,)):
                db.execute(
                    "INSERT INTO drops (owner_id, token, label) VALUES (?, ?, ?)",
                    (owner_id, token, label[:80]),
                )
                return {"token": token, "label": label}
        raise AppError("Не удалось создать комнату обмена, попробуйте снова.", 500)

    @staticmethod
    def active(token: str) -> dict[str, Any] | None:
        row = db.query_one("SELECT * FROM drops WHERE token = ? AND active = 1", (token,))
        return dict(row) if row else None

    @staticmethod
    def by_token(token: str) -> dict[str, Any] | None:
        row = db.query_one("SELECT * FROM drops WHERE token = ?", (token,))
        return dict(row) if row else None

    @staticmethod
    def for_user(user_id: int) -> list[dict[str, Any]]:
        rows = db.query(
            """
            SELECT d.token, d.label, d.active, d.created_at,
                   (SELECT COUNT(*) FROM received_files r WHERE r.drop_token = d.token) AS items
            FROM drops d WHERE d.owner_id = ? ORDER BY d.id DESC
            """,
            (user_id,),
        )
        return db.rows_to_dicts(rows)

    @staticmethod
    def revoke(token: str) -> None:
        db.execute("UPDATE drops SET active = 0 WHERE token = ?", (token,))

    @staticmethod
    def delete(token: str) -> None:
        db.execute("DELETE FROM received_files WHERE drop_token = ?", (token,))
        db.execute("DELETE FROM drops WHERE token = ?", (token,))


class ReceivedFiles:
    SELECT = """
        SELECT r.*, o.username AS owner_name, rc.username AS recipient_name
        FROM received_files r
        JOIN users o ON o.id = r.owner_id
        LEFT JOIN users rc ON rc.id = r.recipient_id
    """

    @staticmethod
    def add(
        drop_token: str, owner_id: int, stored_path: str, original_name: str, size: int, kind: str
    ) -> int:
        cursor = db.execute(
            """
            INSERT INTO received_files
                (drop_token, owner_id, stored_path, original_name, size, kind)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (drop_token, owner_id, stored_path, original_name, size, kind),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def by_id(file_id: int) -> dict[str, Any] | None:
        row = db.query_one(f"{ReceivedFiles.SELECT} WHERE r.id = ?", (file_id,))
        return dict(row) if row else None

    @staticmethod
    def all() -> list[dict[str, Any]]:
        return db.rows_to_dicts(db.query(f"{ReceivedFiles.SELECT} ORDER BY r.id DESC"))

    @staticmethod
    def visible_to(user_id: int) -> list[dict[str, Any]]:
        rows = db.query(
            f"{ReceivedFiles.SELECT} WHERE r.recipient_id = ? OR r.owner_id = ? ORDER BY r.id DESC",
            (user_id, user_id),
        )
        return db.rows_to_dicts(rows)

    @staticmethod
    def in_drop(token: str) -> list[dict[str, Any]]:
        rows = db.query(
            f"{ReceivedFiles.SELECT} WHERE r.drop_token = ? ORDER BY r.id DESC", (token,)
        )
        return db.rows_to_dicts(rows)

    @staticmethod
    def assign(file_id: int, recipient_id: int | None) -> None:
        db.execute("UPDATE received_files SET recipient_id = ? WHERE id = ?", (recipient_id, file_id))

    @staticmethod
    def delete(file_id: int) -> None:
        db.execute("DELETE FROM received_files WHERE id = ?", (file_id,))
