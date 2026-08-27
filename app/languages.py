"""Сопоставление расширений с языками Monaco, MIME-типами и запускаемостью."""

from __future__ import annotations

from pathlib import Path

LANGUAGES: dict[str, str] = {
    "py": "python", "pyw": "python", "pyi": "python",
    "html": "html", "htm": "html",
    "css": "css", "scss": "scss", "less": "less",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "ts": "typescript", "tsx": "typescript", "jsx": "javascript",
    "json": "json", "jsonc": "json",
    "sql": "sql",
    "md": "markdown", "markdown": "markdown",
    "yml": "yaml", "yaml": "yaml",
    "toml": "ini", "ini": "ini", "cfg": "ini", "env": "ini",
    "sh": "shell", "bash": "shell", "zsh": "shell",
    "xml": "xml", "svg": "xml",
    "txt": "plaintext", "log": "plaintext",
    "csv": "plaintext", "tsv": "plaintext",
    "dockerfile": "dockerfile",
    "c": "c", "h": "c", "cpp": "cpp", "hpp": "cpp",
    "go": "go", "rs": "rust", "java": "java", "kt": "kotlin",
    "rb": "ruby", "php": "php", "lua": "lua",
}

TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml", "application/javascript")

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".mov", ".webm", ".avi", ".mkv",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".so", ".dll", ".dylib", ".exe", ".bin", ".db", ".sqlite", ".sqlite3",
    ".xlsx", ".docx", ".pptx",
}

RUNNABLE_PYTHON = {".py", ".pyw"}
RUNNABLE_SQL = {".sql"}
PREVIEWABLE = {".html", ".htm", ".css", ".svg", ".md"}


def language_for(name: str | Path) -> str:
    path = Path(name)
    if path.name.lower() in ("dockerfile", "makefile"):
        return "dockerfile" if path.name.lower() == "dockerfile" else "makefile"
    return LANGUAGES.get(path.suffix.lower().lstrip("."), "plaintext")


def is_binary_name(name: str | Path) -> bool:
    return Path(name).suffix.lower() in BINARY_SUFFIXES


def run_kind(name: str | Path) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in RUNNABLE_PYTHON:
        return "python"
    if suffix in RUNNABLE_SQL:
        return "sql"
    if suffix in (".html", ".htm"):
        return "html"
    if suffix == ".css":
        return "css"
    return "none"


def is_previewable(name: str | Path) -> bool:
    return Path(name).suffix.lower() in PREVIEWABLE
