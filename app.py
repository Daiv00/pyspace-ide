
from flask import Flask, render_template, request, jsonify, redirect
import sqlite3, os
from datetime import datetime

app=Flask(__name__)
DB=os.environ.get("REMINDER_DB","reminders.db")

def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS reminders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        note TEXT DEFAULT '',
        remind_at TEXT NOT NULL,
        done INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    c.commit()
    return c

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/reminders")
def reminders():
    c=db()
    rows=c.execute("SELECT * FROM reminders ORDER BY done, remind_at").fetchall()
    c.close()
    return jsonify([dict(x) for x in rows])

@app.post("/api/reminders")
def add():
    data=request.get_json(force=True)
    title=str(data.get("title","")).strip()
    remind_at=str(data.get("remind_at","")).strip()
    note=str(data.get("note","")).strip()
    if not title or not remind_at:
        return jsonify(error="Название и дата обязательны"),400
    c=db()
    cur=c.execute("INSERT INTO reminders(title,note,remind_at,created_at) VALUES(?,?,?,?)",
                  (title,note,remind_at,datetime.now().isoformat(timespec="seconds")))
    c.commit(); rid=cur.lastrowid; c.close()
    return jsonify(ok=True,id=rid)

@app.patch("/api/reminders/<int:rid>")
def toggle(rid):
    c=db()
    row=c.execute("SELECT done FROM reminders WHERE id=?",(rid,)).fetchone()
    if not row: c.close(); return jsonify(error="Не найдено"),404
    c.execute("UPDATE reminders SET done=? WHERE id=?",(0 if row["done"] else 1,rid))
    c.commit(); c.close()
    return jsonify(ok=True)

@app.delete("/api/reminders/<int:rid>")
def delete(rid):
    c=db(); c.execute("DELETE FROM reminders WHERE id=?",(rid,)); c.commit(); c.close()
    return jsonify(ok=True)

if __name__=="__main__":
    db()

    # PySpace IDE: a Flask web app must not be treated as a finite
    # console program. Set PYSPACE_RUNNER=1 when the IDE only wants
    # to validate/import the project instead of starting a web server.
    if os.environ.get("PYSPACE_RUNNER") == "1":
        print("PySpace: Flask-проект обнаружен. Для веб-запуска используйте серверный режим.")
    else:
        app.run(
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)),
            debug=False,
            use_reloader=False,
        )
