import os,re,sqlite3,secrets,socket,string,subprocess,sys,tempfile,shutil,zipfile,io,base64,datetime
from pathlib import Path
from functools import wraps
from flask import Flask,request,jsonify,session,render_template,send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash,check_password_hash

BASE=Path(__file__).resolve().parent
DATA_ROOT=Path(os.getenv('PYSPACE_DATA_DIR', str(BASE))).resolve()
DB=Path(os.getenv('PYSPACE_DB', str(DATA_ROOT/'data/pyspace.db'))).resolve()
STORAGE=Path(os.getenv('PYSPACE_STORAGE_DIR', str(DATA_ROOT/'storage'))).resolve()
LOCAL_HUB=Path(os.getenv('PYSPACE_LOCAL_HUB_DIR', str(DATA_ROOT/'local_hub'))).resolve()
PORT=int(os.getenv('PORT','8080'))
HOST='0.0.0.0'
TIMEOUT=int(os.getenv('PYSPACE_RUN_TIMEOUT','8'))

app=Flask(__name__)
app.secret_key=os.getenv('PYSPACE_SECRET',secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH']=100*1024*1024

@app.errorhandler(RequestEntityTooLarge)
def too_large(e):
    return jsonify(ok=False,error='ZIP слишком большой. Максимальный размер — 100 МБ.'),413


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
        x=re.sub(r'[<>:"|?*\\x00-\\x1f]','_',x).strip()
        if not x or x in ('.','..'): continue
        safe.append(x)
    if not safe: raise ValueError('Недопустимое имя файла')
    return '/'.join(safe)

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

@app.post('/api/projects/<int:pid>/rename')
@auth
def rename_project(pid):
    p=access(pid,True)
    if not p or p['owner_id']!=user()['id']: return jsonify(error='Только владелец'),403
    n=str((request.get_json() or {}).get('name','')).strip()
    if not n or len(n)>80:return jsonify(error='Некорректное имя'),400
    c=db(); exists=c.execute('SELECT 1 FROM projects WHERE owner_id=? AND name=? AND id<>?',(user()['id'],n,pid)).fetchone()
    if exists:c.close();return jsonify(error='Проект с таким именем уже существует'),409
    c.execute('UPDATE projects SET name=? WHERE id=?',(n,pid));c.commit();c.close();return jsonify(ok=True,name=n)

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
                if not x.is_file():
                    continue
                rel=x.relative_to(b).as_posix()
                if rel == '.upload.zip' or rel.startswith('.packages/') or rel.startswith('__pycache__/') or rel.endswith('.pyc'):
                    continue
                z.write(x,rel)
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
    if not f or not (f.filename or '').lower().endswith('.zip'):
        return jsonify(ok=False,error='Нужен ZIP-файл'),400
    base=re.sub(r'[^\wА-Яа-яЁё ._-]+','_',Path(f.filename).stem).strip(' ._')[:80] or 'Новый проект'
    c=db(); name=base; n=2
    while c.execute('SELECT 1 FROM projects WHERE owner_id=? AND name=?',(user()['id'],name)).fetchone():
        name=f'{base} ({n})'; n+=1
    cur=c.execute('INSERT INTO projects(owner_id,name) VALUES(?,?)',(user()['id'],name))
    pid=cur.lastrowid; c.execute('INSERT INTO members VALUES(?,?,?)',(pid,user()['id'],'owner')); c.commit(); c.close()
    p=pdir(pid); p.mkdir(parents=True,exist_ok=True); tmp=p/'.upload.zip'
    try:
        f.save(str(tmp))
        files=safe_extract_zip(tmp,p)
        return jsonify(ok=True,project_id=pid,project_name=name,files=files,count=len(files),message=f'Проект «{name}» создан. Распаковано файлов: {len(files)}')
    except zipfile.BadZipFile:
        return jsonify(ok=False,error='Файл повреждён или это не ZIP'),400
    except Exception as e:
        app.logger.exception('ZIP import failed')
        return jsonify(ok=False,error=f'Ошибка обработки ZIP: {e}'),500
    finally:
        tmp.unlink(missing_ok=True)

@app.post('/api/projects/<int:project_id>/upload-zip')
def upload_project_zip(project_id):
    if not user(): return jsonify(ok=False,error='Требуется вход'),401
    f=request.files.get('file')
    if not f or not (f.filename or '').lower().endswith('.zip'):
        return jsonify(ok=False,error='Нужен ZIP-файл'),400
    if not access(project_id, True): return jsonify(ok=False,error='Нет прав'),403
    p=pdir(project_id); p.mkdir(parents=True,exist_ok=True); tmp=p/'.upload.zip'
    try:
        f.save(str(tmp)); files=safe_extract_zip(tmp,p)
        return jsonify(ok=True,project_id=project_id,files=files,count=len(files),message=f'Распаковано файлов: {len(files)}')
    except zipfile.BadZipFile:
        return jsonify(ok=False,error='Файл повреждён или это не ZIP'),400
    except Exception as e:
        app.logger.exception('Project ZIP import failed')
        return jsonify(ok=False,error=f'Ошибка обработки ZIP: {e}'),500
    finally:
        tmp.unlink(missing_ok=True)

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


PACKAGE_RE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,150}(?:\[[A-Za-z0-9_,.-]{1,100}\])?(?:==|~=|>=|<=|>|<)?[A-Za-z0-9*_.!+-]{0,80}$")

def project_env(pid):
    work=pdir(pid); work.mkdir(parents=True,exist_ok=True)
    packages=work/'.packages'; packages.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy(); env.update({'PYTHONUNBUFFERED':'1','PYTHONIOENCODING':'utf-8','PYSPACE_PROJECT_ID':str(pid),'PYTHONPATH':str(packages)+os.pathsep+env.get('PYTHONPATH','')})
    return work,env

@app.post('/api/projects/<int:pid>/pip-install')
@auth
def pip_install(pid):
    if not access(pid, True): return jsonify(ok=False,error='Нет прав'),403
    d=request.get_json() or {}; package=str(d.get('package','')).strip()
    if not package or len(package)>220 or not PACKAGE_RE.fullmatch(package):
        return jsonify(ok=False,error='Недопустимое имя пакета. Используйте, например, requests или requests==2.32.3'),400
    work,env=project_env(pid); target=work/'.packages'
    try:
        r=subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-input','--no-cache-dir','--target',str(target),package],cwd=work,capture_output=True,text=True,timeout=120,env=env)
        output=(r.stdout+r.stderr)[-12000:]
        return jsonify(ok=r.returncode==0,returncode=r.returncode,output=output,package=package)
    except subprocess.TimeoutExpired:
        return jsonify(ok=False,returncode=-1,output='⏱ pip install превысил лимит 120 секунд.'),504

# Terminal deliberately accepts a small, explicit command set instead of an arbitrary shell.
TERMINAL_RE=re.compile(r'^[A-Za-z0-9_./:@%+\-=,\[\]]+$')
TERMINAL_CMDS={'pwd','ls','find','cat','head','tail','python','pip','python3'}

def parse_terminal(command):
    import shlex
    if any(x in command for x in [';','&&','||','|','>','<','`','$','\n','\r']):
        raise ValueError('Команды с shell-операторами запрещены')
    args=shlex.split(command)
    if not args or args[0] not in TERMINAL_CMDS:
        raise ValueError('Разрешены: pwd, ls, find, cat, head, tail, python, python3, pip')
    if len(args)>12: raise ValueError('Слишком много аргументов')
    if not all(TERMINAL_RE.fullmatch(a) for a in args): raise ValueError('Недопустимый аргумент')
    if args[0] in ('python','python3'):
        if '-c' in args: raise ValueError('python -c отключён в терминале')
        if '-m' in args:
            if len(args)<3 or args[2] not in ('pip','pip3'): raise ValueError('Разрешён только python -m pip')
        else:
            allowed_flags={'--version','-V'}
            if any(a.startswith('-') and a not in allowed_flags for a in args[1:]): raise ValueError('Флаг Python запрещён')
            for a in args[1:]:
                if not a.startswith('-') and (a.startswith('/') or a=='..' or a.startswith('../') or '/..' in a): raise ValueError('Доступ за пределы проекта запрещён')
    if args[0]=='pip':
        if len(args)>1 and args[1] not in ('list','freeze','show','check','--version','-V'): raise ValueError('Разрешены только pip list, freeze, show, check и --version')
    if args[0] in ('cat','head','tail','find','ls'):
        for a in args[1:]:
            if a.startswith('/') or a=='..' or a.startswith('../') or '/..' in a: raise ValueError('Доступ за пределы проекта запрещён')
    return args

@app.post('/api/terminal')
@auth
def terminal():
    d=request.get_json() or {}; pid=int(d.get('project_id') or 0); command=str(d.get('command','')).strip()
    if not access(pid, True): return jsonify(ok=False,error='Нет прав'),403
    if not command: return jsonify(ok=False,error='Введите команду'),400
    if len(command)>4000:return jsonify(ok=False,error='Команда слишком длинная'),413
    try: args=parse_terminal(command)
    except ValueError as e:return jsonify(ok=False,error=str(e)),400
    work,env=project_env(pid)
    try:
        r=subprocess.run(args,cwd=work,capture_output=True,text=True,timeout=30,env=env)
        return jsonify(ok=r.returncode==0,returncode=r.returncode,output=(r.stdout+r.stderr)[-16000:])
    except subprocess.TimeoutExpired:
        return jsonify(ok=False,returncode=-1,output='⏱ Команда превысила лимит 30 секунд.'),504

@app.post('/api/run')
@auth
def run():
    d=request.get_json() or {}; pid=int(d.get('project_id') or 0)
    try:path=clean(d.get('path') or 'main.py')
    except ValueError as e:return jsonify(error=str(e)),400
    if not access(pid):return jsonify(error='Нет доступа'),403
    try:target=fpath(pid,path)
    except ValueError as e:return jsonify(error=str(e)),400
    if not target.is_file():return jsonify(error='Файл не найден'),404
    ext=target.suffix.lower()
    if ext in ('.html','.htm'):return jsonify(ok=True,kind='html',output='HTML готов к предпросмотру')
    if ext=='.css':return jsonify(ok=True,kind='css',output='CSS готов к предпросмотру')
    if ext=='.sql':
        with tempfile.TemporaryDirectory(prefix='pyspace_sql_') as td:
            dbfile=Path(td)/'project.sqlite3'; con=sqlite3.connect(dbfile); con.row_factory=sqlite3.Row
            try:
                script=target.read_text(encoding='utf-8',errors='replace'); cur=con.cursor(); cur.executescript(script); con.commit(); rows=[]
                for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 20").fetchall():
                    try: rows.extend([dict(r) for r in con.execute(f'SELECT * FROM "{t[0].replace(chr(34),chr(34)*2)}" LIMIT 100').fetchall()])
                    except Exception: pass
                return jsonify(ok=True,kind='sql',output='SQL выполнен успешно\n'+('\n'.join(str(r) for r in rows) if rows else 'Изменения применены.'))
            except Exception as e:return jsonify(ok=False,kind='sql',output=str(e))
            finally:con.close()
    if ext not in ('.py','.pyw'):return jsonify(error='Для запуска поддерживаются Python, HTML, CSS и SQL'),400
    stdin_data=str(d.get('stdin',''))
    if len(stdin_data)>20000:return jsonify(error='Тестовые данные слишком большие'),413
    with tempfile.TemporaryDirectory(prefix='pyspace_') as td:
        work=Path(td)/'project'; shutil.copytree(pdir(pid),work,ignore=shutil.ignore_patterns('.packages','__pycache__','*.pyc','.upload.zip'))
        script=work/path
        packages=pdir(pid)/'.packages'
        env={'PATH':os.environ.get('PATH',''),'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1','HOME':str(work),'PYTHONPATH':str(packages)}
        try:
            # No -I: project-local .packages must be importable.
            r=subprocess.run([sys.executable,str(script)],cwd=work,input=stdin_data,capture_output=True,text=True,timeout=TIMEOUT,env=env)
            return jsonify(ok=r.returncode==0,kind='python',returncode=r.returncode,output=(r.stdout+r.stderr)[-16000:])
        except subprocess.TimeoutExpired:return jsonify(ok=False,returncode=-1,output=f'⏱ Превышен лимит {TIMEOUT} сек.\nВозможна бесконечная input()/петля.'),504

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
