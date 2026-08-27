"""Smoke-тесты PySpace IDE: основной путь пользователя целиком.

Запуск:  python -m pytest tests -q      (или просто python tests/test_smoke.py)
Тесты работают в отдельной временной папке и не трогают ваши данные.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="pyspace-tests-"))
os.environ.update(
    PYSPACE_ENV="development",
    PYSPACE_DATA_DIR=str(TMP),
    PYSPACE_SECRET="test-secret",
    PYSPACE_ADMIN_USER="",
    PYSPACE_ADMIN_PASSWORD="",
    PYSPACE_ENABLE_REGISTRATION="1",
    PYSPACE_RUN_TIMEOUT="30",
)

from app import create_app  # noqa: E402

app = create_app()
app.config.update(TESTING=True)


def payload(response):
    return json.loads(response.data.decode("utf-8"))


def test_full_flow() -> None:
    client = app.test_client()

    # --- страницы доступны без входа ---
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/robots.txt").status_code == 200

    # --- регистрация: первый пользователь становится администратором ---
    response = client.post("/api/auth/register", json={"username": "denis", "password": "supersecret"})
    data = payload(response)
    assert response.status_code == 200 and data["ok"], data
    assert data["user"]["role"] == "admin", data

    # --- проект из шаблона ---
    response = client.post("/api/projects", json={"name": "Демо", "template": "python"})
    data = payload(response)
    assert data["ok"], data
    project = data["project"]["id"]

    tree = payload(client.get(f"/api/projects/{project}/tree"))["tree"]
    assert any(node["path"] == "main.py" for node in tree), tree

    # --- запись файла и запуск кода ---
    code = "value = sum(range(10))\nprint('сумма', value)\nprint(input())\n"
    assert payload(client.put(f"/api/projects/{project}/file", json={"path": "main.py", "content": code}))["ok"]

    result = payload(client.post(f"/api/projects/{project}/run", json={"path": "main.py", "stdin": "привет"}))["result"]
    assert result["returncode"] == 0, result
    assert "сумма 45" in result["output"], result
    assert "привет" in result["output"], result

    # --- папки, копирование, перемещение, удаление ---
    assert payload(client.post(f"/api/projects/{project}/file", json={"path": "пакет/util.py", "type": "file", "content": "X = 1\n"}))["ok"]
    assert payload(client.post(f"/api/projects/{project}/move", json={"from": "пакет/util.py", "to": "пакет/helpers.py"}))["ok"]
    assert payload(client.post(f"/api/projects/{project}/copy", json={"from": "пакет/helpers.py", "to": "пакет/helpers_copy.py"}))["ok"]
    file_data = payload(client.get(f"/api/projects/{project}/file?path=пакет/helpers_copy.py"))["file"]
    assert file_data["content"] == "X = 1\n"
    assert payload(client.delete(f"/api/projects/{project}/file", json={"path": "пакет/helpers_copy.py"}))["ok"]

    # --- защита от выхода за пределы проекта ---
    for bad in ("../../secret.txt", "/etc/passwd", "пакет/../../x"):
        response = client.get(f"/api/projects/{project}/file?path={bad}")
        assert response.status_code >= 400, bad

    # --- поиск по файлам ---
    hits = payload(client.get(f"/api/projects/{project}/search?q=сумма"))["hits"]
    assert any(hit["path"] == "main.py" for hit in hits), hits

    # --- загрузка файла и скачивание проекта в ZIP ---
    upload = {"files": (io.BytesIO("данные".encode("utf-8")), "заметка.txt"), "target": "пакет"}
    response = client.post(f"/api/projects/{project}/upload", data=upload, content_type="multipart/form-data")
    assert payload(response)["ok"], payload(response)

    response = client.get(f"/api/projects/{project}/download")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        names = archive.namelist()
    assert "main.py" in names and "пакет/заметка.txt" in names, names

    # --- импорт ZIP как нового проекта ---
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("index.html", "<h1>Привет</h1>")
        archive.writestr("assets/style.css", "body{color:red}")
    buffer.seek(0)
    response = client.post(
        "/api/projects/import-zip",
        data={"file": (buffer, "site.zip"), "name": "Сайт"},
        content_type="multipart/form-data",
    )
    imported = payload(response)
    assert imported["ok"], imported
    site = imported["project"]["id"]
    site_tree = payload(client.get(f"/api/projects/{site}/tree"))["tree"]
    assert any(node["path"] == "assets/style.css" for node in site_tree), site_tree

    # --- живой предпросмотр по токену ---
    token = payload(client.get(f"/api/projects/{site}"))["project"]["preview_token"]
    response = client.get(f"/preview/{token}/index.html")
    assert response.status_code == 200 and "Привет" in response.data.decode("utf-8")
    assert "sandbox" in response.headers.get("Content-Security-Policy", "")
    assert payload(client.get(f"/preview/{token}/__meta"))["ok"]

    # --- комната обмена: QR, анонимная загрузка, хранилище ---
    drop = payload(client.post("/api/drops", json={"label": "С телефона"}))["drop"]
    assert client.get(f"/api/drops/{drop['token']}/qr.png").status_code == 200
    assert client.get(f"/d/{drop['token']}").status_code == 200
    assert client.get(f"/s/{drop['token']}").status_code == 301

    anonymous = app.test_client()  # без входа — так же, как телефон
    response = anonymous.post(
        f"/api/drops/{drop['token']}/upload",
        data={"files": (io.BytesIO(b"photo-bytes"), "photo.jpg"), "text": "и сообщение"},
        content_type="multipart/form-data",
    )
    assert payload(response)["ok"], payload(response)

    files = payload(client.get("/api/drops/vault/files"))["files"]
    assert len(files) >= 2, files

    # --- админка ---
    overview = payload(client.get("/api/admin/overview"))
    assert overview["stats"]["users"] == 1, overview
    created = payload(client.post("/api/admin/users", json={"username": "гость", "password": "guestpass1", "role": "user"}))
    assert created["ok"], created

    # --- терминал: сообщаем состояние ---
    terminal = payload(client.get(f"/api/projects/{project}/terminal"))
    assert "websocket" in terminal, terminal

    # --- pip доступен (ставим маленький пакет только если есть сеть) ---
    listing = payload(client.get(f"/api/projects/{project}/pip"))
    assert listing["ok"], listing

    # --- выход ---
    assert payload(client.post("/api/auth/logout"))["ok"]
    assert client.get("/api/projects").status_code == 401

    print("Все smoke-тесты прошли ✓")


if __name__ == "__main__":
    test_full_flow()
