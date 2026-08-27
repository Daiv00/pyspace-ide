"""Запускает Flask- или FastAPI-приложение из файла, в котором нет своего сервера.

Зачем отдельный файл: `flask --app site:app` и `uvicorn site:app` требуют имя
модуля, и оно легко сталкивается со стандартной библиотекой (файл `site.py`,
`code.py`, `types.py` — обычные имена в пользовательских проектах). Здесь файл
загружается прямо по пути, поэтому конфликтов имён нет.

Запуск: python -u webapp_boot.py <путь к файлу> <имя переменной> <flask|fastapi> <порт>
"""

from __future__ import annotations

import sys

# Первым делом убираем из sys.path папку самого загрузчика: иначе его соседи
# могут перекрыть стандартные модули, которые нужны Flask и uvicorn.
if sys.path and sys.path[0]:
    sys.path.pop(0)

import importlib.util  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402


def load_app(script: Path, variable: str):
    """Загрузить файл как модуль и достать из него объект приложения."""
    # Корень проекта и папка файла — чтобы работали `import соседний_модуль`.
    # Добавляем в КОНЕЦ sys.path: так файл с именем вроде `types.py` или `code.py`
    # не перекроет стандартную библиотеку, которая нужна Flask, FastAPI и pydantic.
    project_root = os.getenv("PYSPACE_WEBAPP_ROOT") or str(Path.cwd())
    for entry in (project_root, str(script.parent)):
        if entry and entry not in sys.path:
            sys.path.append(entry)

    # Имя модуля с префиксом, чтобы не перекрыть стандартную библиотеку,
    # и не равное "__main__", чтобы не сработал блок `if __name__ == "__main__"`.
    name = f"pyspace_webapp_{script.stem}"
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Не удалось загрузить файл: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    application = getattr(module, variable, None)
    if application is None:
        raise SystemExit(
            f"В файле {script.name} нет переменной «{variable}». "
            "Проверьте, что приложение создаётся на верхнем уровне файла."
        )
    return application


def main() -> int:
    if len(sys.argv) < 5:
        print("Использование: webapp_boot.py <файл> <переменная> <flask|fastapi> <порт>")
        return 2

    script = Path(sys.argv[1]).resolve()
    variable, kind, port = sys.argv[2], sys.argv[3], int(sys.argv[4])
    host = os.getenv("HOST", "0.0.0.0")

    # Сначала поднимаем сам фреймворк — до того, как в sys.path появится папка проекта.
    if kind == "fastapi":
        import fastapi  # noqa: F401
        import uvicorn
    else:
        import flask  # noqa: F401

    application = load_app(script, variable)

    if kind == "fastapi":

        print(f"[pyspace] uvicorn: {script.name}:{variable} на порту {port}", flush=True)
        uvicorn.run(application, host=host, port=port, log_level="info")
        return 0

    print(f"[pyspace] flask: {script.name}:{variable} на порту {port}", flush=True)
    application.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
