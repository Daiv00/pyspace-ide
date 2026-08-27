"""Проверка резервных копий без обращения к GitHub: архив → удаление → возврат.

Запуск: python tests/test_backup.py  (нужны зависимости из requirements.txt)
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYSPACE_ENV", "development")
os.environ.setdefault("PYSPACE_SECRET", "test-secret")
os.environ["PYSPACE_DATA_DIR"] = str(ROOT / "var-test")
os.environ["PYSPACE_BACKUP_REPO"] = "test/backup"
os.environ["PYSPACE_BACKUP_TOKEN"] = "test-token"

from app import backup  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    data = settings.data_dir
    if data.exists():
        shutil.rmtree(data)
    settings.ensure_dirs()

    project = settings.storage_dir / "project_1"
    (project / "web").mkdir(parents=True, exist_ok=True)
    (project / "main.py").write_text("print('привет')\n", encoding="utf-8")
    (project / "web" / "index.html").write_text("<h1>ок</h1>\n", encoding="utf-8")
    (project / ".packages").mkdir(exist_ok=True)
    (project / ".packages" / "huge.bin").write_bytes(b"0" * 5000)
    settings.db_path.write_bytes(b"SQLite format 3\x00fake")

    # Копия в память вместо GitHub.
    storage: dict[str, bytes] = {}
    backup.upload = lambda blob: storage.__setitem__("blob", blob) or {"ok": True}
    backup.download = lambda: storage.get("blob")

    first = backup.backup_now(force=True)
    assert not first["skipped"], "первая копия должна создаться"
    print(f"копия создана: {first['size']} байт")

    names = []
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(storage["blob"])) as archive:
        names = archive.getnames()
    assert "pyspace.db" in names, "в копии нет базы"
    assert "projects/project_1/main.py" in names, "в копии нет файла проекта"
    assert not any(".packages" in name for name in names), "в копию попали пакеты pip"
    print(f"в архиве {len(names)} записей, лишнее отброшено")

    skipped = backup.backup_now(force=False)
    assert skipped["skipped"], "неизменённые данные не должны заливаться повторно"
    print("повторная заливка без изменений пропущена")

    shutil.rmtree(settings.storage_dir)
    settings.db_path.unlink()
    result = backup.restore_now()
    assert result["found"], "копия не найдена"
    assert (project / "main.py").read_text(encoding="utf-8") == "print('привет')\n"
    assert (project / "web" / "index.html").exists()
    assert settings.db_path.exists()
    print(f"восстановлено файлов: {result['restored']}")

    shutil.rmtree(data, ignore_errors=True)
    print("Проверка резервных копий пройдена ✓")


if __name__ == "__main__":
    main()
