import io
import json
import zipfile
import shutil
from werkzeug.exceptions import RequestEntityTooLarge
import os,re,sqlite3,secrets,socket,string,subprocess,sys,tempfile,shutil,zipfile,io,base64,datetime
import threading, time, http.client, mimetypes
from pathlib import Path
from functools import wraps
from flask import Flask,request,jsonify,session,render_template,send_file,Response
from werkzeug.security import generate_password_hash,check_password_hash

BASE=Path(__file__).resolve().parent
DATA_ROOT=Path(os.getenv('PYSPACE_DATA_DIR', str(BASE))).resolve()
DB=Path(os.getenv('PYSPACE_DB', str(DATA_ROOT/'data/pyspace.db'))).resolve()
STORAGE=Path(os.getenv('PYSPACE_STORAGE_DIR', str(DATA_ROOT/'storage'))).resolve()
LOCAL_HUB=Path(os.getenv('PYSPACE_LOCAL_HUB_DIR', str(DATA_ROOT/'local_hub'))).resolve()
PORT=int(os.getenv('PORT','10000'))
HOST='0.0.0.0'
TIMEOUT=max(1,int(os.getenv('PYSPACE_RUN_TIMEOUT','30')))

app=Flask(__name__)
app.secret_key=os.getenv('PYSPACE_SECRET',secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH']=100*1024*1024

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    return jsonify(ok=False,error='ZIP/файл слишком большой (максимум 100 МБ)'),413

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    app.logger.exception('Unhandled server error')
    return jsonify(ok=False,error='Внутренняя ошибка сервера',details=str(e)),500

LANGS={'py':'python','pyw':'python','html':'html','htm':'html','css':'css','sql':'sql','js':'javascript','json':'json','txt':'plaintext'}

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    (BASE/'data').mkdir(exist_ok=True); STORAGE.mkdir(exist_ok=True); LOCAL_HUB.mkdir(exist_ok=True)
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL,name TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS members(project_id INTEGER,user_id INTEGER,role TEXT NOT NULL DEFAULT 'editor',PRIMARY KEY(project_id,user_id),FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS local_shares(id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL,token TEXT UNIQUE NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,active INTEGER NOT NULL DEFAULT 1,FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS received_files(id INTEGER PRIMARY KEY AUTOINCREMENT,share_token TEXT NOT NULL,owner_id INTEGER NOT NULL,recipient_id INTEGER,stored_path TEXT NOT NULL,original_name TEXT NOT NULL,size INTEGER NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(recipient_id) REFERENCES users(id) ON DELETE SET NULL);
    CREATE INDEX IF NOT EXISTS idx_received_recipient ON received_files(recipient_id);
    ''')
    env_user=os.getenv('PYSPACE_ADMIN_USER','').strip()
    env_pw=os.getenv('PYSPACE_ADMIN_PASSWORD','')
    if env_user and env_pw:
        existing=c.execute('SELECT id,role FROM users WHERE username=?',(env_user,)).fetchone()
        if not existing:
            c.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(env_user,generate_password_hash(env_pw),'admin'))
        elif existing['role']!='admin':
            # Keep the configured Render admin account as admin even when an old SQLite DB exists.
            c.execute('UPDATE users SET role=? WHERE id=?',('admin',existing['id']))
        c.commit()
    c.close()

def user():
    if 'uid' not in session:return None
    c=db(); u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone(); c.close(); return u

def auth(f):
    @wraps(f)
    def w(*a,**k):
        if not user(): return jsonify(error='Требуется авторизация'),401
        return f(*a,**k)
    return w

def adm(f):
    @wraps(f)
    def w(*a,**k):
        u=user()
        if not u:return jsonify(error='Требуется авторизация'),401
        if u['role']!='admin':return jsonify(error='Нужны права admin'),403
        return f(*a,**k)
    return w

def clean(p):
    p=str(p or '').replace('\\','/').strip('/')
    parts=[x for x in p.split('/') if x not in ('','.')]
    if not parts or any(x=='..' for x in parts) or len(p)>240:
        raise ValueError('Недопустимый путь')
    # Keep normal Unicode filenames, but remove characters that are unsafe on Windows/Linux.
    safe=[]
    for x in parts:
        x=re.sub(r'[<>:"|?*\x00-\x1f]','_',x).strip()
        if not x or x in ('.','..'): continue
        safe.append(x)
    if not safe: raise ValueError('Недопустимое имя файла')
    return '/'.join(safe)

def pdir(pid): return STORAGE/f'project_{pid}'

# Live web previews. Each preview runs inside this same PySpace instance and is
# reverse-proxied through /web-preview/<token>/..., so users do not need Render
# or another external deployment to see their project.
WEB_PREVIEWS = {}
WEB_PREVIEWS_LOCK = threading.Lock()
WEB_PREVIEW_TTL = int(os.getenv('PYSPACE_WEB_PREVIEW_TTL', '1800'))
WEB_PREVIEW_STARTUP = float(os.getenv('PYSPACE_WEB_PREVIEW_STARTUP', '8'))

def _stop_web_preview(token):
    with WEB_PREVIEWS_LOCK:
        item = WEB_PREVIEWS.pop(token, None)
    if item:
        try:
            item['proc'].terminate()
            item['proc'].wait(timeout=3)
        except Exception:
            try: item['proc'].kill()
            except Exception: pass

def _web_preview_cleaner():
    while True:
        time.sleep(30)
        now = time.time()
        with WEB_PREVIEWS_LOCK:
            items = list(WEB_PREVIEWS.items())
        for token, item in items:
            if item['proc'].poll() is not None or now - item['last'] > WEB_PREVIEW_TTL:
                _stop_web_preview(token)

threading.Thread(target=_web_preview_cleaner, daemon=True).start()

def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

def _start_web_preview(pid, path):
    if not access(pid):
        raise PermissionError('Нет доступа')
    project = pdir(pid).resolve()
    script = fpath(pid, path)
    if not script.is_file():
        raise FileNotFoundError('Файл не найден')

    # Only Python web applications are started here. HTML/CSS are handled by
    # the existing sandboxed preview.
    source = script.read_text(encoding='utf-8', errors='replace')
    flask_like = ('from flask import' in source or 'import flask' in source or
                  'Flask(' in source or 'app.run(' in source)
    if not flask_like:
        raise ValueError('Не удалось определить Flask-приложение. Для HTML используйте «Предпросмотр».')

    # Reuse a live preview for the same project/file.
    with WEB_PREVIEWS_LOCK:
        for token, item in WEB_PREVIEWS.items():
            if item['pid'] == pid and item['path'] == path and item['proc'].poll() is None:
                item['last'] = time.time()
                return token, item['port']

    port = _free_port()
    env = os.environ.copy()
    env.update({
        'PORT': str(port),
        'PYTHONUNBUFFERED': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
    })
    # Gunicorn is already part of PySpace's production dependencies.
    cmd = [sys.executable, '-m', 'gunicorn',
           '--bind', f'127.0.0.1:{port}',
           '--workers', '1',
           '--timeout', '120',
           '--access-logfile', '-',
           '--error-logfile', '-',
           f'{Path(path).with_suffix("").as_posix().replace("/", ".")}:app']

    proc = subprocess.Popen(
        cmd, cwd=project, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=(os.name != 'nt')
    )
    token = secrets.token_urlsafe(24)
    item = {'pid': pid, 'path': path, 'port': port, 'proc': proc, 'last': time.time()}
    with WEB_PREVIEWS_LOCK:
        WEB_PREVIEWS[token] = item

    deadline = time.time() + WEB_PREVIEW_STARTUP
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=0.4)
            c.request('GET', '/')
            r = c.getresponse()
            r.read(64)
            c.close()
            ready = True
            break
        except Exception:
            time.sleep(0.12)
    if not ready:
        _stop_web_preview(token)
        raise RuntimeError('Не удалось запустить веб-приложение. Проверьте app.py и зависимости проекта.')

    return token, port

def _proxy_web_preview(token, subpath):
    with WEB_PREVIEWS_LOCK:
        item = WEB_PREVIEWS.get(token)
        if not item:
            return None
        if item['proc'].poll() is not None:
            WEB_PREVIEWS.pop(token, None)
            return None
        item['last'] = time.time()
        port = item['port']

    target_path = '/' + (subpath or '')
    if request.query_string:
        target_path += '?' + request.query_string.decode('utf-8', 'replace')
    body = request.get_data()
    headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ('host', 'content-length', 'connection'):
            continue
        if lk in ('cookie', 'content-type', 'authorization', 'accept', 'user-agent'):
            headers[k] = v
    headers['Host'] = f'127.0.0.1:{port}'
    headers['X-Forwarded-Proto'] = request.scheme
    headers['X-Forwarded-Host'] = request.host

    try:
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        conn.request(request.method, target_path, body=body or None, headers=headers)
        upstream = conn.getresponse()
        data = upstream.read()
        out_headers = []
        for k, v in upstream.getheaders():
            lk = k.lower()
            if lk in ('connection', 'transfer-encoding', 'content-length', 'server', 'date'):
                continue
            if lk == 'location' and v.startswith('/'):
                v = f'/web-preview/{token}{v}'
            out_headers.append((k, v))
        out_headers.append(('Cache-Control', 'no-store'))
        return Response(data, status=upstream.status, headers=out_headers)
    except Exception as e:
        return jsonify(error='Веб-приложение остановилось или не отвечает', detail=str(e)), 502
    finally:
        try: conn.close()
        except Exception: pass


def fpath(pid,p):
    p=clean(p); base=pdir(pid).resolve(); x=(base/p).resolve()
    if base!=x and base not in x.parents: raise ValueError('Недопустимый путь')
    return x

def access(pid,write=False):
    u=user(); c=db(); r=c.execute('SELECT p.*,CASE WHEN p.owner_id=? THEN "owner" ELSE m.role END access FROM projects p LEFT JOIN members m ON m.project_id=p.id AND m.user_id=? WHERE p.id=? AND (p.owner_id=? OR m.user_id=?)',(u['id'],u['id'],pid,u['id'],u['id'])).fetchone(); c.close()
    return r if r and (not write or r['access']!='viewer') else None

def language_for(path):
    return LANGS.get(Path(path).suffix.lower().lstrip('.'),'plaintext')

def lan_ips():
    forced=os.getenv('PYSPACE_LAN_HOST','').strip()
    if forced: return [forced]
    ips=[]
    try:
        for x in socket.gethostbyname_ex(socket.gethostname())[2]:
            if x.startswith(('10.','192.168.','172.16.','172.17.','172.18.','172.19.','172.2','172.3')) and x not in ips: ips.append(x)
    except Exception: pass
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); x=s.getsockname()[0]; s.close()
        if x not in ips and x not in ('127.0.0.1','0.0.0.0'): ips.insert(0,x)
    except Exception: pass
    return ips or ['127.0.0.1']

def share_dir(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{7,80}',token): raise ValueError('bad token')
    return LOCAL_HUB/f'share_{token}'

def share_row(token):
    c=db(); r=c.execute('SELECT * FROM local_shares WHERE token=? AND active=1',(token,)).fetchone(); c.close(); return r

def share_path(token,name):
    name=clean(name); base=share_dir(token).resolve(); x=(base/name).resolve()
    if base!=x and base not in x.parents: raise ValueError('Недопустимый путь')
    return x

def received_file_row(fid):
    c=db(); r=c.execute('SELECT rf.*,u.username owner_name,ru.username recipient_name FROM received_files rf JOIN users u ON u.id=rf.owner_id LEFT JOIN users ru ON ru.id=rf.recipient_id WHERE rf.id=?',(fid,)).fetchone(); c.close(); return r

@app.get('/')
def index(): return render_template('index.html')
@app.get('/health')
def health(): return 'ok',200

@app.get('/api/me')
def me():
    u=user(); return jsonify(authenticated=bool(u),username=u['username'] if u else None,role=u['role'] if u else None)

@app.post('/api/register')
def register():
    d=request.get_json() or {}; n=str(d.get('username','')).strip(); pw=str(d.get('password',''))
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,32}',n): return jsonify(error='Логин 3–32 символа'),400
    if len(pw)<8: return jsonify(error='Пароль минимум 8 символов'),400
    c=db()
    try:
        role='admin' if c.execute('SELECT COUNT(*) n FROM users').fetchone()['n']==0 else 'user'
        c.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(n,generate_password_hash(pw),role)); c.commit()
    except sqlite3.IntegrityError:
        c.close(); return jsonify(error='Пользователь уже существует'),409
    c.close(); return jsonify(ok=True,role=role)

@app.post('/api/login')
def login():
    d=request.get_json() or {}; c=db(); u=c.execute('SELECT * FROM users WHERE username=?',(str(d.get('username','')).strip(),)).fetchone(); c.close()
    if not u or not check_password_hash(u['password_hash'],str(d.get('password',''))): return jsonify(error='Неверный логин или пароль'),401
    session.clear(); session['uid']=u['id']; return jsonify(ok=True,username=u['username'],role=u['role'])

@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)

@app.get('/api/projects')
@auth
def projects():
    u=user(); c=db(); rows=c.execute('SELECT p.id,p.name,p.owner_id,p.created_at,CASE WHEN p.owner_id=? THEN "owner" ELSE m.role END access FROM projects p LEFT JOIN members m ON m.project_id=p.id AND m.user_id=? WHERE p.owner_id=? OR m.user_id=? ORDER BY p.id DESC',(u['id'],u['id'],u['id'],u['id'])).fetchall(); c.close(); return jsonify([dict(x) for x in rows])

@app.post('/api/projects')
@auth
def create_project():
    n=str((request.get_json() or {}).get('name','')).strip()
    if not n or len(n)>80:return jsonify(error='Некорректное имя'),400
    c=db(); cur=c.execute('INSERT INTO projects(owner_id,name) VALUES(?,?)',(user()['id'],n)); pid=cur.lastrowid; c.execute('INSERT INTO members VALUES(?,?,?)',(pid,user()['id'],'owner')); c.commit(); c.close()
    pdir(pid).mkdir(parents=True); fpath(pid,'main.py').write_text("print('Hello from PySpace!')",encoding='utf-8'); return jsonify(id=pid,name=n)

@app.delete('/api/projects/<int:pid>')
@auth
def delete_project(pid):
    p=access(pid)
    if not p or p['owner_id']!=user()['id']:return jsonify(error='Только владелец'),403
    c=db(); c.execute('DELETE FROM projects WHERE id=?',(pid,)); c.commit(); c.close(); shutil.rmtree(pdir(pid),ignore_errors=True); return jsonify(ok=True)

@app.get('/api/projects/<int:pid>/files')
@auth
def files(pid):
    if not access(pid):return jsonify(error='Нет доступа'),403
    b=pdir(pid); b.mkdir(parents=True,exist_ok=True)
    return jsonify([{'path':x.relative_to(b).as_posix(),'size':x.stat().st_size,'language':language_for(x.name)} for x in sorted(b.rglob('*')) if x.is_file()])

@app.get('/api/projects/<int:pid>/files/<path:path>')
@auth
def getfile(pid,path):
    if not access(pid):return jsonify(error='Нет доступа'),403
    try:x=fpath(pid,path)
    except ValueError as e:return jsonify(error=str(e)),400
    if not x.is_file():return jsonify(error='Файл не найден'),404
    return jsonify(path=clean(path),content=x.read_text(encoding='utf-8',errors='replace'),language=language_for(x.name))

@app.post('/api/projects/<int:pid>/files')
@auth
def savefile(pid):
    if not access(pid,True):return jsonify(error='Нет прав'),403
    d=request.get_json() or {}; content=str(d.get('content',''))
    try:x=fpath(pid,d.get('path'))
    except ValueError as e:return jsonify(error=str(e)),400
    if len(content.encode())>2*1024*1024:return jsonify(error='Файл слишком большой'),413
    x.parent.mkdir(parents=True,exist_ok=True); x.write_text(content,encoding='utf-8'); return jsonify(ok=True)

@app.post('/api/projects/<int:pid>/upload')
@auth
def upload_files(pid):
    if not access(pid,True): return jsonify(error='Нет прав'),403
    incoming=request.files.getlist('files')
    if not incoming:return jsonify(error='Файлы не выбраны'),400
    saved=[]
    for f in incoming:
        name=(f.filename or '').replace('\\','/').strip('/')
        if not name: continue
        try: x=fpath(pid,name)
        except ValueError: continue
        x.parent.mkdir(parents=True,exist_ok=True); f.save(x); saved.append(x.relative_to(pdir(pid)).as_posix())
    return jsonify(ok=True,files=saved)

@app.get('/api/projects/<int:pid>/download/<path:path>')
@auth
def download_file(pid,path):
    if not access(pid):return jsonify(error='Нет доступа'),403
    try:x=fpath(pid,path)
    except ValueError as e:return jsonify(error=str(e)),400
    if not x.is_file():return jsonify(error='Файл не найден'),404
    return send_file(x,as_attachment=True,download_name=x.name)

@app.get('/api/projects/<int:pid>/download.zip')
@auth
def download_project(pid):
    if not access(pid):return jsonify(error='Нет доступа'),403
    b=pdir(pid)
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
        if b.exists():
            for x in b.rglob('*'):
                if x.is_file(): z.write(x,x.relative_to(b).as_posix())
    mem.seek(0); return send_file(mem,as_attachment=True,download_name=f'pyspace_project_{pid}.zip',mimetype='application/zip')

@app.get('/api/projects/<int:pid>/preview/<path:path>')
@auth
def preview_file(pid,path):
    if not access(pid): return jsonify(error='Нет доступа'),403
    try:
        x=fpath(pid,path)
    except ValueError as e:
        return jsonify(error=str(e)),400
    if not x.is_file(): return jsonify(error='Файл не найден'),404
    ext=x.suffix.lower()
    if ext in ('.html','.htm'):
        # Serve the actual file from the project, so relative CSS/JS/images work.
        return send_file(x, mimetype='text/html; charset=utf-8')
    if ext=='.css':
        return Response(x.read_text(encoding='utf-8',errors='replace'),
                        mimetype='text/css')
    # Any other asset the previewed page references relatively (JS, images,
    # fonts, JSON, etc.) — serve it with its guessed mimetype so the page
    # actually works, not just renders bare markup.
    mt=mimetypes.guess_type(x.name)[0] or 'application/octet-stream'
    return send_file(x, mimetype=mt)

@app.delete('/api/projects/<int:pid>/files')
@auth
def delfile(pid):
    if not access(pid,True):return jsonify(error='Нет прав'),403
    try:x=fpath(pid,(request.get_json() or {}).get('path'))
    except ValueError as e:return jsonify(error=str(e)),400
    if x.exists():x.unlink()
    return jsonify(ok=True)

@app.post('/api/projects/<int:pid>/rename')
@auth
def rename(pid):
    if not access(pid,True):return jsonify(error='Нет прав'),403
    d=request.get_json() or {}
    try:a=fpath(pid,d.get('old_path')); b=fpath(pid,d.get('new_path'))
    except ValueError as e:return jsonify(error=str(e)),400
    if not a.exists():return jsonify(error='Файл не найден'),404
    b.parent.mkdir(parents=True,exist_ok=True); a.rename(b); return jsonify(ok=True)

@app.post('/api/projects/<int:pid>/share')
@auth
def share(pid):
    p=access(pid)
    if not p or p['owner_id']!=user()['id']:return jsonify(error='Только владелец'),403
    d=request.get_json() or {}; c=db(); u=c.execute('SELECT id FROM users WHERE username=?',(str(d.get('username','')).strip(),)).fetchone()
    if not u:c.close();return jsonify(error='Пользователь не найден'),404
    role=d.get('role','editor')
    if role not in ('editor','viewer'):c.close();return jsonify(error='Роль editor/viewer'),400
    c.execute('INSERT INTO members VALUES(?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role',(pid,u['id'],role)); c.commit(); c.close(); return jsonify(ok=True)

@app.get('/api/server')
@auth
def server():
    scheme=request.headers.get('X-Forwarded-Proto','https' if request.is_secure else 'http').split(',')[0]
    host=request.headers.get('X-Forwarded-Host',request.host).split(',')[0]
    cloud=f'{scheme}://{host}'
    local_mode=not bool(request.headers.get('X-Forwarded-Host') or request.headers.get('X-Forwarded-Proto'))
    lans=[f'http://{x}:{PORT}' for x in lan_ips()] if local_mode else []
    return jsonify(cloud_url=cloud,lan_urls=lans,port=PORT,local_mode=local_mode)

@app.post('/api/local-share')
@auth
def create_local_share():
    alphabet=string.ascii_letters+string.digits
    while True:
        token=''.join(secrets.choice(alphabet) for _ in range(7))
        c=db()
        exists=c.execute('SELECT 1 FROM local_shares WHERE token=?',(token,)).fetchone()
        if not exists:
            c.execute('INSERT INTO local_shares(owner_id,token) VALUES(?,?)',(user()['id'],token)); c.commit(); c.close()
            break
        c.close()
    share_dir(token).mkdir(parents=True,exist_ok=True)
    local_mode=not bool(request.headers.get('X-Forwarded-Host') or request.headers.get('X-Forwarded-Proto'))
    base=request.host_url.rstrip('/')
    primary=base+f'/s/{token}'
    urls=[f'http://{x}:{PORT}/s/{token}' for x in lan_ips()] if local_mode else []
    return jsonify(token=token,urls=urls,cloud_url=primary,share_url=primary,local_mode=local_mode,port=PORT)

@app.post('/api/quick-share')
@auth
def quick_share():
    return create_local_share()

@app.get('/api/my-shares')
@auth
def my_shares():
    c=db(); rows=c.execute('SELECT token,created_at,active FROM local_shares WHERE owner_id=? ORDER BY id DESC',(user()['id'],)).fetchall(); c.close()
    result=[]
    for r in rows:
        b=share_dir(r['token']); total=sum(x.stat().st_size for x in b.rglob('*') if x.is_file()) if b.exists() else 0
        result.append({'token':r['token'],'created_at':r['created_at'],'active':bool(r['active']),'files_size':total})
    return jsonify(result)

@app.get('/api/local-share/<token>/health')
def local_share_health(token):
    return jsonify(ok=bool(share_row(token)),token=token)

@app.get('/api/local-share/<token>')
def local_share_info(token):
    r=share_row(token)
    if not r:return jsonify(error='Ссылка недействительна'),404
    b=share_dir(token); b.mkdir(parents=True,exist_ok=True)
    items=[]
    for x in sorted(b.rglob('*')):
        if x.is_file(): items.append({'path':x.relative_to(b).as_posix(),'size':x.stat().st_size})
    return jsonify(active=True,files=items,token=token)

@app.post('/api/local-share/<token>/upload')
def local_share_upload(token):
    r=share_row(token)
    if not r:
        return jsonify(ok=False,error='Ссылка недействительна или обмен закрыт'),404
    b=share_dir(token); b.mkdir(parents=True,exist_ok=True)
    incoming=request.files.getlist('files')
    text=request.form.get('text','')
    text_name=request.form.get('text_name','message.txt')
    saved=[]
    errors=[]
    c=db()

    def store_file(x, original):
        rel=x.relative_to(b).as_posix()
        size=x.stat().st_size
        c.execute(
            'INSERT INTO received_files(share_token,owner_id,recipient_id,stored_path,original_name,size) VALUES(?,?,?,?,?,?)',
            (token,r['owner_id'],None,rel,original,size)
        )
        saved.append({'path':rel,'name':original,'size':size})

    if text.strip():
        try:
            name=clean(text_name or 'message.txt')
            # Text is always a file so it is preserved exactly like an uploaded file.
            x=share_path(token,name)
            x.parent.mkdir(parents=True,exist_ok=True)
            x.write_text(text,encoding='utf-8')
            store_file(x,name)
        except Exception as e:
            errors.append('Текст: '+str(e))

    for f in incoming:
        original=(f.filename or '').replace('\\','/').split('/')[-1].strip()
        if not original:
            continue
        try:
            name=clean(original)
            x=share_path(token,name)
            x.parent.mkdir(parents=True,exist_ok=True)
            f.save(str(x))
            store_file(x,original)
        except Exception as e:
            errors.append(f'{original}: {e}')

    if not saved:
        c.close()
        return jsonify(ok=False,error='Не удалось сохранить данные',details=errors),400

    c.commit(); c.close()
    meta=b/'.pyspace_manifest.json'
    manifest={'updated_at':datetime.datetime.utcnow().isoformat()+'Z','files':[
        {'path':x.relative_to(b).as_posix(),'size':x.stat().st_size}
        for x in sorted(b.rglob('*')) if x.is_file() and x.name!='.pyspace_manifest.json'
    ]}
    meta.write_text(__import__('json').dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return jsonify(ok=True,files=saved,errors=errors,message=f'Сохранено: {len(saved)}')


def safe_extract_zip(zip_path, destination):
    destination=Path(destination).resolve()
    extracted=[]
    with zipfile.ZipFile(zip_path,'r') as z:
        for info in z.infolist():
            name=info.filename.replace('\\','/')
            parts=[p for p in name.split('/') if p not in ('','.')]
            if not parts or any(p=='..' for p in parts):
                continue
            target=(destination.joinpath(*parts)).resolve()
            if target != destination and destination not in target.parents:
                continue
            if info.is_dir():
                target.mkdir(parents=True,exist_ok=True)
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as srcf, open(target,'wb') as dstf:
                shutil.copyfileobj(srcf,dstf)
            extracted.append('/'.join(parts))
    return extracted

@app.post('/api/projects/upload-zip')
def upload_project_zip_auto():
    if not user(): return jsonify(ok=False,error='Требуется вход'),401
    f=request.files.get('file')
    if not f or not f.filename.lower().endswith('.zip'): return jsonify(ok=False,error='Нужен ZIP-файл'),400
    base=re.sub(r'[^\wА-Яа-яЁё ._-]+','_',Path(f.filename).stem).strip(' ._')[:80] or 'Новый проект'
    name=base; n=2; c=db()
    while c.execute('SELECT 1 FROM projects WHERE owner_id=? AND name=?',(user()['id'],name)).fetchone():
        name=f'{base} ({n})'; n+=1
    cur=c.execute('INSERT INTO projects(owner_id,name) VALUES(?,?)',(user()['id'],name))
    pid=cur.lastrowid; c.commit(); c.close()
    p=pdir(pid); p.mkdir(parents=True,exist_ok=True); tmp=p/'.upload.zip'; f.save(tmp)
    try: files=safe_extract_zip(tmp,p)
    except zipfile.BadZipFile:
        tmp.unlink(missing_ok=True); c=db(); c.execute('DELETE FROM projects WHERE id=?',(pid,)); c.commit(); c.close()
        return jsonify(ok=False,error='Файл повреждён или это не ZIP'),400
    finally: tmp.unlink(missing_ok=True)
    return jsonify(ok=True,project_id=pid,project_name=name,files=files,count=len(files),
                    message=f'Проект «{name}» создан. Распаковано файлов: {len(files)}')

@app.post('/api/projects/<int:project_id>/upload-zip')
def upload_project_zip(project_id):
    if not user(): return jsonify(ok=False,error='Требуется вход'),401
    f=request.files.get('file')
    if not f or not f.filename.lower().endswith('.zip'): return jsonify(ok=False,error='Нужен ZIP-файл'),400
    c=db(); row=c.execute('SELECT * FROM projects WHERE id=? AND owner_id=?',(project_id,user()['id'])).fetchone(); c.close()
    if not row: return jsonify(ok=False,error='Проект не найден'),404
    p=pdir(project_id); p.mkdir(parents=True,exist_ok=True); tmp=p/'.upload.zip'; f.save(tmp)
    try: files=safe_extract_zip(tmp,p)
    except zipfile.BadZipFile: return jsonify(ok=False,error='Файл повреждён или это не ZIP'),400
    finally: tmp.unlink(missing_ok=True)
    return jsonify(ok=True,project_id=project_id,project_name=row['name'],files=files,count=len(files),
                    message=f'Распаковано файлов: {len(files)}')

@app.get('/api/received-files')
@auth
def received_files():
    u=user(); c=db()
    if u['role']=='admin':
        rows=c.execute('SELECT rf.*,u.username owner_name,ru.username recipient_name FROM received_files rf JOIN users u ON u.id=rf.owner_id LEFT JOIN users ru ON ru.id=rf.recipient_id ORDER BY rf.id DESC').fetchall()
    else:
        rows=c.execute('SELECT rf.*,u.username owner_name,ru.username recipient_name FROM received_files rf JOIN users u ON u.id=rf.owner_id LEFT JOIN users ru ON ru.id=rf.recipient_id WHERE rf.recipient_id=? ORDER BY rf.id DESC',(u['id'],)).fetchall()
    c.close(); return jsonify([dict(x) for x in rows])

@app.post('/api/admin/received-files/<int:fid>/assign')
@adm
def assign_received_file(fid):
    d=request.get_json() or {}; username=str(d.get('username','')).strip()
    c=db(); f=c.execute('SELECT id FROM received_files WHERE id=?',(fid,)).fetchone()
    if not f:c.close(); return jsonify(error='Файл не найден'),404
    ru=c.execute('SELECT id,username FROM users WHERE username=?',(username,)).fetchone()
    if not ru:c.close(); return jsonify(error='Пользователь не найден'),404
    c.execute('UPDATE received_files SET recipient_id=? WHERE id=?',(ru['id'],fid)); c.commit(); c.close(); return jsonify(ok=True,username=ru['username'])

@app.delete('/api/admin/received-files/<int:fid>')
@adm
def delete_received_file(fid):
    f=received_file_row(fid)
    if not f:return jsonify(error='Файл не найден'),404
    try: p=share_path(f['share_token'],f['stored_path']); p.unlink(missing_ok=True)
    except Exception: pass
    c=db(); c.execute('DELETE FROM received_files WHERE id=?',(fid,)); c.commit(); c.close(); return jsonify(ok=True)

@app.get('/api/received-files/<int:fid>/download')
@auth
def download_received(fid):
    u=user(); f=received_file_row(fid)
    if not f:return jsonify(error='Файл не найден'),404
    if u['role']!='admin' and f['recipient_id']!=u['id']:return jsonify(error='Нет доступа к этому файлу'),403
    try:p=share_path(f['share_token'],f['stored_path'])
    except ValueError:return jsonify(error='Недопустимый путь'),400
    if not p.is_file():return jsonify(error='Файл отсутствует на диске'),404
    return send_file(p,as_attachment=True,download_name=f['original_name'])

@app.get('/api/local-share/<token>/download/<path:path>')
def local_share_download(token,path):
    if not share_row(token):return jsonify(error='Ссылка недействительна'),404
    try:x=share_path(token,path)
    except ValueError as e:return jsonify(error=str(e)),400
    if not x.is_file():return jsonify(error='Файл не найден'),404
    return send_file(x,as_attachment=True,download_name=x.name)

@app.get('/api/local-share/<token>/qr')
def local_share_qr(token):
    r=share_row(token)
    if not r:return jsonify(error='Ссылка недействительна'),404
    try:
        import qrcode
        url=request.host_url.rstrip('/')+f'/s/{token}'
        img=qrcode.make(url)
        mem=io.BytesIO(); img.save(mem,format='PNG'); mem.seek(0)
        return send_file(mem,mimetype='image/png')
    except Exception as e:
        return jsonify(error=str(e)),500

@app.get('/s/<token>')
def short_share(token):
    if not share_row(token):
        return render_template('share.html',error='Ссылка недействительна или закрыта'),404
    return render_template('share.html',token=token)

@app.get('/share/<token>')
def share_page(token):
    if not share_row(token):return render_template('share.html',error='Ссылка недействительна или закрыта'),404
    return render_template('share.html',token=token)

@app.post('/api/local-share/<token>/revoke')
@auth
def revoke_local_share(token):
    r=share_row(token)
    if not r:return jsonify(error='Ссылка не найдена'),404
    if r['owner_id']!=user()['id']:return jsonify(error='Только владелец'),403
    c=db(); c.execute('UPDATE local_shares SET active=0 WHERE token=?',(token,)); c.commit(); c.close(); return jsonify(ok=True)



@app.get('/api/projects/<int:pid>/preview-assets/<path:path>')
@auth
def preview_asset(pid,path):
    if not access(pid): return jsonify(error='Нет доступа'),403
    try: x=fpath(pid,path)
    except ValueError as e: return jsonify(error=str(e)),400
    if not x.is_file(): return jsonify(error='Файл не найден'),404
    return send_file(x)

@app.post('/api/web-preview/start')
@auth
def start_web_preview():
    d = request.get_json() or {}
    pid = int(d.get('project_id') or 0)
    path = clean(d.get('path') or 'app.py')
    try:
        token, port = _start_web_preview(pid, path)
        return jsonify(ok=True, kind='web', token=token,
                       url=f'/web-preview/{token}/')
    except PermissionError as e:
        return jsonify(error=str(e)), 403
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        return jsonify(error=str(e)), 400

@app.post('/api/web-preview/<token>/stop')
@auth
def stop_web_preview(token):
    with WEB_PREVIEWS_LOCK:
        item = WEB_PREVIEWS.get(token)
    if not item or not access(item['pid']):
        return jsonify(error='Предпросмотр не найден'), 404
    _stop_web_preview(token)
    return jsonify(ok=True)

@app.route('/web-preview/<token>/', defaults={'subpath': ''},
             methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD'])
@app.route('/web-preview/<token>/<path:subpath>',
           methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS','HEAD'])
def web_preview(token, subpath):
    return _proxy_web_preview(token, subpath) or (jsonify(error='Предпросмотр не найден'), 404)

@app.post('/api/run')
@auth
def run():
    d=request.get_json() or {}; pid=int(d.get('project_id') or 0); path=clean(d.get('path') or 'main.py')
    if not access(pid):return jsonify(error='Нет доступа'),403
    try:target=fpath(pid,path)
    except ValueError as e:return jsonify(error=str(e)),400
    if not target.exists():return jsonify(error='Файл не найден'),404
    ext=target.suffix.lower()
    if ext=='.html' or ext=='.htm':
        return jsonify(ok=True,kind='html',output='HTML готов к предпросмотру')
    if ext=='.css': return jsonify(ok=True,kind='css',output='CSS готов к предпросмотру')
    if ext=='.sql':
        with tempfile.TemporaryDirectory(prefix='pyspace_sql_') as td:
            dbfile=Path(td)/'project.sqlite3'; con=sqlite3.connect(dbfile); con.row_factory=sqlite3.Row
            try:
                script=target.read_text(encoding='utf-8',errors='replace'); cur=con.cursor(); cur.executescript(script); con.commit()
                rows=[]
                for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 20").fetchall():
                    try: rows.extend([dict(r) for r in con.execute(f'SELECT * FROM "{t[0].replace(chr(34),chr(34)*2)}" LIMIT 100').fetchall()])
                    except Exception: pass
                con.close(); return jsonify(ok=True,kind='sql',output='SQL выполнен успешно\n'+('\n'.join(str(r) for r in rows) if rows else 'Изменения применены.'))
            except Exception as e:
                con.close(); return jsonify(ok=False,kind='sql',output=str(e))
    if ext not in ('.py','.pyw'): return jsonify(error='Для запуска поддерживаются Python, HTML, CSS и SQL'),400
    stdin_data=str(d.get('stdin',''))
    if len(stdin_data)>20000:return jsonify(error='Тестовые данные слишком большие'),413

    # Web applications (Flask/FastAPI/uvicorn/http.server) are servers by design:
    # running them as a console program would wait forever and falsely look like
    # an input()/infinite-loop timeout. Test Flask apps without calling app.run().
    try:
        source = target.read_text(encoding='utf-8', errors='replace')
    except Exception:
        source = ''
    web_markers = (
        'from flask import', 'import flask', 'Flask(', '.run(host=', '.run(port=',
        'FastAPI(', 'uvicorn.run(', 'app.run(', 'serve_forever('
    )
    is_web = any(marker in source for marker in web_markers)
    if is_web:
        try:
            token, port = _start_web_preview(pid, path)
            return jsonify(
                ok=True,
                kind='web',
                token=token,
                url=f'/web-preview/{token}/',
                output=(
                    '🌐 Веб-приложение запущено и открыто в живом предпросмотре ниже.\n'
                    'Сервер продолжает работать в фоне, пока вы не закроете предпросмотр '
                    'или не запустите файл заново.'
                )
            )
        except PermissionError as e:
            return jsonify(ok=False, kind='web', error=str(e)), 403
        except (ValueError, FileNotFoundError) as e:
            # e.g. not actually a Flask app (FastAPI/uvicorn/http.server aren't
            # supported by this live-preview launcher).
            return jsonify(ok=False, kind='web', error=str(e), output=str(e))
        except RuntimeError as e:
            return jsonify(ok=False, kind='web', error=str(e), output=str(e))

    with tempfile.TemporaryDirectory(prefix='pyspace_') as td:
        work=Path(td)/'project'; shutil.copytree(pdir(pid),work); script=work/path
        env={'PATH':os.environ.get('PATH',''),'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1','HOME':str(work)}
        try:
            popen_kwargs={}
            if os.name == 'nt':
                popen_kwargs['creationflags']=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)
            else:
                popen_kwargs['start_new_session']=True
            r=subprocess.run(
                [sys.executable,'-I',str(script)],
                cwd=work,
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
                env=env,
                **popen_kwargs
            )
            return jsonify(
                ok=r.returncode==0,
                kind='python',
                returncode=r.returncode,
                output=(r.stdout+r.stderr)[-16000:]
            )
        except subprocess.TimeoutExpired:
            return jsonify(
                ok=False,
                kind='python',
                returncode=-1,
                error='TIMEOUT',
                output=(
                    f'⏱ Превышен лимит выполнения {TIMEOUT} сек.\n'
                    'Если программа использует input(), укажите все значения во вкладке «Ввод» перед запуском.\n'
                    'Если это бесконечный цикл, остановите/исправьте цикл.'
                )
            )

@app.get('/api/debug/session')
@auth
def debug_session():
    u=user()
    return jsonify(authenticated=True,username=u['username'],role=u['role'],admin_configured=bool(os.getenv('PYSPACE_ADMIN_USER','').strip()))


@app.get('/admin')
def admin_page():
    u=user()
    if not u:
        return jsonify(error='Требуется авторизация'),401
    if u['role']!='admin':
        return jsonify(error='Нужны права admin'),403
    return render_template('index.html')

@app.get('/api/admin/users')
@adm
def users():
    c=db();r=c.execute('SELECT id,username,role,created_at FROM users ORDER BY id').fetchall();c.close();return jsonify([dict(x) for x in r])
@app.post('/api/admin/users/<int:uid>/role')
@adm
def role(uid):
    r=(request.get_json() or {}).get('role')
    if r not in ('user','admin'):return jsonify(error='Неверная роль'),400
    c=db();c.execute('UPDATE users SET role=? WHERE id=?',(r,uid));c.commit();c.close();return jsonify(ok=True)
@app.delete('/api/admin/users/<int:uid>')
@adm
def deluser(uid):
    if uid==user()['id']:return jsonify(error='Нельзя удалить себя'),400
    c=db();c.execute('DELETE FROM users WHERE id=?',(uid,));c.commit();c.close();return jsonify(ok=True)

init_db()
if __name__=='__main__':app.run(host=HOST,port=PORT,debug=False)
