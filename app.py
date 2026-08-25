import os,re,sqlite3,secrets,socket,subprocess,sys,tempfile,shutil,zipfile,io,base64,datetime
from pathlib import Path
from functools import wraps
from flask import Flask,request,jsonify,session,render_template,send_file
from werkzeug.security import generate_password_hash,check_password_hash

BASE=Path(__file__).resolve().parent
DB=BASE/'data/pyspace.db'
STORAGE=BASE/'storage'
LOCAL_HUB=BASE/'local_hub'
PORT=int(os.getenv('PORT','8080'))
HOST='0.0.0.0'
TIMEOUT=int(os.getenv('PYSPACE_RUN_TIMEOUT','8'))

app=Flask(__name__)
app.secret_key=os.getenv('PYSPACE_SECRET',secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH']=20*1024*1024

LANGS={'py':'python','pyw':'python','html':'html','htm':'html','css':'css','sql':'sql','js':'javascript','json':'json','txt':'plaintext'}

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    (BASE/'data').mkdir(exist_ok=True); STORAGE.mkdir(exist_ok=True)
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL,name TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS members(project_id INTEGER,user_id INTEGER,role TEXT NOT NULL DEFAULT 'editor',PRIMARY KEY(project_id,user_id),FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS local_shares(id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL,token TEXT UNIQUE NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,active INTEGER NOT NULL DEFAULT 1,FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE);
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
    if not p or '..' in p.split('/') or len(p)>240 or not re.fullmatch(r'[\wА-Яа-яЁё ._\-/]+',p): raise ValueError('Недопустимый путь')
    return p

def pdir(pid): return STORAGE/f'project_{pid}'

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
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,80}',token): raise ValueError('bad token')
    return LOCAL_HUB/f'share_{token}'

def share_row(token):
    c=db(); r=c.execute('SELECT * FROM local_shares WHERE token=? AND active=1',(token,)).fetchone(); c.close(); return r

def share_path(token,name):
    name=clean(name); base=share_dir(token).resolve(); x=(base/name).resolve()
    if base!=x and base not in x.parents: raise ValueError('Недопустимый путь')
    return x

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
    if not access(pid):return jsonify(error='Нет доступа'),403
    try:x=fpath(pid,path)
    except ValueError as e:return jsonify(error=str(e)),400
    if not x.is_file():return jsonify(error='Файл не найден'),404
    return jsonify(path=clean(path),content=x.read_text(encoding='utf-8',errors='replace'),language=language_for(x.name))

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
    token=secrets.token_urlsafe(24).replace('-','_').replace('~','_')
    c=db(); c.execute('INSERT INTO local_shares(owner_id,token) VALUES(?,?)',(user()['id'],token)); c.commit(); c.close()
    share_dir(token).mkdir(parents=True,exist_ok=True)
    local_mode=not bool(request.headers.get('X-Forwarded-Host') or request.headers.get('X-Forwarded-Proto'))
    urls=[f'http://{x}:{PORT}/share/{token}' for x in lan_ips()] if local_mode else []
    return jsonify(token=token,urls=urls,cloud_url=request.host_url.rstrip('/')+f'/share/{token}',local_mode=local_mode,port=PORT)

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
    if not share_row(token):return jsonify(error='Ссылка недействительна'),404
    incoming=request.files.getlist('files')
    text=request.form.get('text','')
    saved=[]
    if text.strip():
        name=(request.form.get('text_name') or 'message.txt').strip()
        x=share_path(token,name); x.parent.mkdir(parents=True,exist_ok=True); x.write_text(text,encoding='utf-8'); saved.append(x.relative_to(share_dir(token)).as_posix())
    for f in incoming:
        name=(f.filename or '').replace('\\','/').strip('/')
        if not name:continue
        try:x=share_path(token,name)
        except ValueError:continue
        x.parent.mkdir(parents=True,exist_ok=True); f.save(x); saved.append(x.relative_to(share_dir(token)).as_posix())
    if not saved:return jsonify(error='Нет данных для загрузки'),400
    return jsonify(ok=True,files=saved)

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
        url=os.getenv('PYSPACE_LAN_URL','').strip() or f'http://{lan_ips()[0]}:{PORT}/share/{token}'
        img=qrcode.make(url)
        mem=io.BytesIO(); img.save(mem,format='PNG'); mem.seek(0)
        return send_file(mem,mimetype='image/png')
    except Exception as e:
        return jsonify(error=str(e)),500

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
    with tempfile.TemporaryDirectory(prefix='pyspace_') as td:
        work=Path(td)/'project'; shutil.copytree(pdir(pid),work); script=work/path
        env={'PATH':os.environ.get('PATH',''),'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1','HOME':str(work)}
        try:
            r=subprocess.run([sys.executable,'-I',str(script)],cwd=work,input=stdin_data,capture_output=True,text=True,timeout=TIMEOUT,env=env)
            return jsonify(ok=r.returncode==0,kind='python',returncode=r.returncode,output=(r.stdout+r.stderr)[-16000:])
        except subprocess.TimeoutExpired:return jsonify(ok=False,returncode=-1,output=f'⏱ Превышен лимит {TIMEOUT} сек.\nВозможна бесконечная input()/петля.')

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
