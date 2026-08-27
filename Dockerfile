# PySpace IDE — образ для Render (и для локального запуска через Docker).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYSPACE_ENV=production \
    PYSPACE_GEVENT=1 \
    PORT=8080

# bash и git нужны настоящему терминалу, curl — для health-check.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bash git curl ca-certificates procps tini unzip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Пользователь без прав root: код в терминале выполняется от его имени.
# Каталог /data специально НЕ создаётся: он появляется только когда в Render
# подключён Persistent Disk. По его наличию приложение понимает, что данные
# можно хранить постоянно.
RUN useradd --create-home --shell /bin/bash pyspace \
 && mkdir -p /app/var \
 && chown -R pyspace:pyspace /app

USER pyspace
ENV HOME=/home/pyspace \
    SHELL=/bin/bash

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# Один воркер + gevent: PTY-сессии и WebSocket живут в одном процессе,
# timeout 0 — чтобы gunicorn не убивал долгие соединения терминала.
CMD ["sh", "-c", "gunicorn -k gevent -w 1 --timeout 0 --graceful-timeout 20 --keep-alive 65 --access-logfile - --error-logfile - -b 0.0.0.0:${PORT} wsgi:app"]
