# PySpace IDE v1

MVP мини-IDE: авторизация, роли, проекты, физическое локальное хранилище `storage/`, вложенные папки, редактирование Monaco, Ctrl+S, запуск Python, terminal, project sharing, LAN URL.

## SnapDeploy
Artifact: `Python App (.zip)`; Port: `8080`; Start Command: `python app.py`.

Можно задать `PYSPACE_ADMIN_USER` и `PYSPACE_ADMIN_PASSWORD`; если база пустая, они создадут admin. Если их нет, первый зарегистрированный пользователь становится admin.

## LAN
Приложение слушает `0.0.0.0:8080`. Кнопка LAN показывает локальный IP. Телефон в той же Wi-Fi сети открывает `http://IP:8080`.

## Security
Runner сейчас запускает Python subprocess на сервере и предназначен для доверенной LAN/прототипа. Для публичного сервиса обязательно заменить runner на sandbox (Docker/Firecracker, no network, limits, non-root, temporary FS).
