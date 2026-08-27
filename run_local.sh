#!/usr/bin/env bash
# Локальный запуск PySpace IDE (Linux / macOS).
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

if [ ! -d .venv ]; then
  echo "→ Создаём виртуальное окружение .venv"
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ Устанавливаем зависимости"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

export PYSPACE_ENV=development
export PYSPACE_SECRET=${PYSPACE_SECRET:-dev-secret-not-for-production}
export PYSPACE_ADMIN_USER=${PYSPACE_ADMIN_USER:-admin}
export PYSPACE_ADMIN_PASSWORD=${PYSPACE_ADMIN_PASSWORD:-admin12345}
export PORT=${PORT:-8080}

echo
echo "  PySpace IDE → http://127.0.0.1:${PORT}"
echo "  Логин: ${PYSPACE_ADMIN_USER}  Пароль: ${PYSPACE_ADMIN_PASSWORD}"
echo "  Остановить: Ctrl+C"
echo

exec python -m flask --app wsgi:app run --host 0.0.0.0 --port "${PORT}" --reload
