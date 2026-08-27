"""Быстрая проверка PTY-терминала по WebSocket (локально, не для деплоя)."""

import json
import sys

import simple_websocket

url = "ws://localhost:8099/ws/terminal/1"
ws = simple_websocket.Client(url)
ws.send(json.dumps({"cols": 100, "rows": 30}))

seen = []
ws.send(json.dumps({"type": "input", "data": "pwd && echo ПРИВЕТ-ИЗ-PTY\n"}))
for _ in range(40):
    try:
        raw = ws.receive(timeout=3)
    except Exception as exc:  # noqa: BLE001
        print("ошибка:", exc)
        break
    if raw is None:
        break
    msg = json.loads(raw)
    seen.append(msg.get("type"))
    if msg.get("type") == "output":
        text = msg.get("data", "")
        sys.stdout.write(text)
        if "ПРИВЕТ-ИЗ-PTY" in text and text.count("ПРИВЕТ-ИЗ-PTY") >= 2:
            break

ws.send(json.dumps({"type": "close"}))
ws.close()
print("\n\nтипы сообщений:", seen[:12])
