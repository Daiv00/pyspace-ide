let ed=null,project=null,file=null,role='user';
const $=id=>document.getElementById(id);
const api=async(url,options={})=>{const opts={...options,credentials:'same-origin',headers:{...(options.body&&!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(options.headers||{})}};let r;try{r=await fetch(url,opts)}catch(e){throw new Error('Нет соединения с сервером: '+e.message)}const text=await r.text();let d={};try{d=text?JSON.parse(text):{}}catch(e){if(!r.ok)throw new Error('HTTP '+r.status)}if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d};
function msg(t){$('msg').textContent=t?.message||String(t||'')}function setBusy(v){$('loginBtn').disabled=v;$('registerBtn').disabled=v}
async function login(){const username=$('username').value.trim(),password=$('password').value;if(!username||!password)return msg('Введите логин и пароль');setBusy(true);msg('Выполняется вход...');try{start(await api('/api/login',{method:'POST',body:JSON.stringify({username,password})}))}catch(e){msg(e)}finally{setBusy(false)}}
async function register(){const username=$('username').value.trim(),password=$('password').value;if(!username||!password)return msg('Введите логин и пароль');setBusy(true);msg('Создание аккаунта...');try{const d=await api('/api/register',{method:'POST',body:JSON.stringify({username,password})});msg(d.role==='admin'?'Аккаунт создан как admin. Теперь войдите.':'Аккаунт создан. Теперь нажмите «Войти».')}catch(e){msg(e)}finally{setBusy(false)}}
function start(m){$('auth').classList.add('hidden');$('app').classList.remove('hidden');$('who').textContent=m.username||'';role=m.role||'user';$('admin').style.display=role==='admin'?'inline-flex':'none';loadProjects().catch(msg)}
async function boot(){try{const m=await api('/api/me');if(m.authenticated)start(m)}catch(e){msg(e)}}
function initEditor(){if(typeof require==='undefined'){msg('Редактор не загрузился. Обновите страницу.');boot();return}require.config({paths:{vs:'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs'}});require(['vs/editor/editor.main'],()=>{ed=monaco.editor.create($('editor'),{value:'',language:'python',theme:'vs-dark',automaticLayout:true,minimap:{enabled:false},fontSize:14,tabSize:4,wordWrap:'on',padding:{top:12,bottom:12},scrollBeyondLastLine:false});boot()},()=>boot())}
async function logout(){try{await api('/api/logout',{method:'POST'})}finally{location.reload()}}
async function loadProjects(){const ps=await api('/api/projects');$('projects').innerHTML=ps.map(p=>`<div class="project ${project?.id===p.id?'active':''}" data-pid="${p.id}"><span>▸ ${esc(p.name)}</span><small>${esc(p.access)}</small></div>`).join('');$('projects').querySelectorAll('.project').forEach((el,i)=>el.onclick=()=>selectProject(ps[i]));if(!project&&ps[0])await selectProject(ps[0])}
async function selectProject(p){project=p;file=null;await loadProjects();await loadFiles();closeSidebar()}
async function loadFiles(){const fs=await api(`/api/projects/${project.id}/files`);$('files').innerHTML=fs.map(f=>`<div class="file ${file?.path===f.path?'active':''}"><span>${fileIcon(f.language)} ${esc(f.path)}</span></div>`).join('');$('files').querySelectorAll('.file').forEach((el,i)=>el.onclick=()=>openFile(fs[i].path));if(!file&&fs[0])await openFile(fs[0].path)}
function fileIcon(l){return ({python:'🐍',html:'◇',css:'◈',sql:'▤',javascript:'JS',json:'{}',plaintext:'·'})[l]||'·'}
async function openFile(p){file=await api(`/api/projects/${project.id}/files/${encodeURIComponent(p)}`);if(ed){ed.setValue(file.content);setLanguage(file.language)}$('tab').textContent=file.path;await loadFiles()}
function setLanguage(l){$('langSelect').value=l;if(ed){monaco.editor.setModelLanguage(ed.getModel(),l)}}
async function newProject(){let n=prompt('Название проекта');if(!n)return;project=await api('/api/projects',{method:'POST',body:JSON.stringify({name:n})});file=null;await loadProjects();await loadFiles()}
async function newFile(){if(!project)return alert('Выберите проект');let p=prompt('Путь, например src/utils.py');if(!p)return;await api(`/api/projects/${project.id}/files`,{method:'POST',body:JSON.stringify({path:p,content:''})});await openFile(p)}
async function save(){if(!project||!file||!ed)return;await api(`/api/projects/${project.id}/files`,{method:'POST',body:JSON.stringify({path:file.path,content:ed.getValue()})});out('✓ Сохранено: '+file.path)}
async function uploadFiles(list){if(!project||!list.length)return;const fd=new FormData();[...list].forEach(f=>fd.append('files',f));try{const r=await api(`/api/projects/${project.id}/upload`,{method:'POST',body:fd});out('✓ Загружено:\n'+r.files.join('\n'));await loadFiles();if(r.files[0])await openFile(r.files[0])}catch(e){out('✕ '+e.message)}}
async function downloadCurrent(){downloadMenu('file')}
async function downloadZip(){downloadMenu('project')}
async function renameProject(){if(!project)return alert('Выберите проект');const n=prompt('Новое название проекта',project.name);if(!n||n.trim()===project.name)return;try{await api(`/api/projects/${project.id}/rename`,{method:'POST',body:JSON.stringify({name:n.trim()})});project.name=n.trim();await loadProjects();}catch(e){alert(e.message)}}
async function deleteFile(){if(!file||!confirm('Удалить файл?'))return;await api(`/api/projects/${project.id}/files`,{method:'DELETE',body:JSON.stringify({path:file.path})});file=null;await loadFiles()}
async function renameFile(){if(!file)return;let p=prompt('Новый путь',file.path);if(!p||p===file.path)return;await api(`/api/projects/${project.id}/rename`,{method:'POST',body:JSON.stringify({old_path:file.path,new_path:p})});await openFile(p)}
async function run(){if(!project||!file)return;await save();out('▶ Выполнение...');try{const d=await api('/api/run',{method:'POST',body:JSON.stringify({project_id:project.id,path:file.path,stdin:$('stdin').value})});out((d.ok?'✓ Успешно\n\n':'✕ Ошибка\n\n')+(d.output||''));if(d.kind==='html'||d.kind==='css')preview()}catch(e){out('✕ '+e.message)}}
async function preview(){if(!project||!file)return;const ext=file.path.toLowerCase().split('.').pop();if(!['html','htm','css'].includes(ext))return out('Предпросмотр доступен для HTML/CSS.');await save();const d=await api(`/api/projects/${project.id}/preview/${encodeURIComponent(file.path)}`);let html;if(ext==='html')html=d.content;else html=`<!doctype html><html><head><meta charset="utf-8"><style>${d.content}</style></head><body><div class="preview-demo"><h1>PySpace CSS Preview</h1><p>Это предпросмотр CSS.</p><button>Button</button></div></body></html>`;modal(`<h2>Предпросмотр</h2><iframe class="preview" sandbox="allow-scripts" srcdoc="${escAttr(html)}"></iframe>`)}
async function share(){if(!project)return;let u=prompt('Логин пользователя');if(!u)return;let r=prompt('Роль: editor или viewer','editor');if(!r)return;try{await api(`/api/projects/${project.id}/share`,{method:'POST',body:JSON.stringify({username:u,role:r})});alert('Доступ выдан')}catch(e){alert(e.message)}}
async function localShare(){try{const d=await api('/api/local-share',{method:'POST'});const lan=d.urls?.[0]||'';const main=lan||d.cloud_url;modal(`<div class="share-modal"><div class="eyebrow">FILE DROP</div><h2>Обмен файлами</h2><p class="muted">Эту ссылку можно открыть на другом устройстве. В локальном режиме устройства должны быть в одной Wi‑Fi сети.</p><div class="share-link">${esc(main||'')}</div>${d.token?`<img class="qr" src="/api/local-share/${d.token}/qr" alt="QR-код">`:''}<div class="share-urls">${(d.urls||[]).map(x=>`<div>${esc(x)}</div>`).join('')}</div><p class="muted small">${d.local_mode?'Локальный Wi‑Fi режим активен.':'Сейчас PySpace работает в облаке Render. Для локального Wi‑Fi обмена запустите PySpace на компьютере в вашей сети.'}</p><button class="primary" onclick="copyText('${escAttr(main)}')">Копировать ссылку</button></div>`)}catch(e){alert('Обмен: '+e.message)}}
async function copyText(t){try{await navigator.clipboard.writeText(t);alert('Ссылка скопирована')}catch(e){prompt('Скопируйте ссылку:',t)}}
async function receivedFiles(){try{const rows=await api('/api/received-files');const isAdmin=role==='admin';let html='<div class="received-head"><div><div class="eyebrow">FILE VAULT</div><h2>Переданные файлы</h2><p class="muted">'+(isAdmin?'Все файлы, отправленные через QR/обмен. Только администратор может выдавать доступ.':'Файлы, которые администратор выдал вашему аккаунту.')+'</p></div></div>';if(!rows.length){html+='<div class="empty-state">Пока переданных файлов нет.</div>'}else{html+='<div class="received-list">'+rows.map(f=>{const who=f.recipient_name?('→ '+esc(f.recipient_name)):'не выдан';const controls=isAdmin?`<button class="tool-btn" onclick="assignReceived(${f.id})">${f.recipient_name?'Изменить':'Выдать'}</button><button class="tool-btn danger-text" onclick="deleteReceived(${f.id})">Удалить</button>`:'';return `<div class="received-item"><div class="received-main"><b>📄 ${esc(f.original_name)}</b><small>${fmtSize(f.size)} · от ${esc(f.owner_name)} · ${who}</small></div><div class="received-actions"><a class="tool-btn" href="/api/received-files/${f.id}/download">↓ Скачать</a>${controls}</div></div>`}).join('')+'</div>'}modal(html)}catch(e){alert('Не удалось открыть хранилище: '+e.message)}}
async function assignReceived(id){const u=prompt('Введите логин пользователя, которому выдать файл:');if(!u)return;try{await api(`/api/admin/received-files/${id}/assign`,{method:'POST',body:JSON.stringify({username:u})});receivedFiles()}catch(e){alert(e.message)}}
async function deleteReceived(id){if(!confirm('Удалить переданный файл без возможности восстановления?'))return;try{await api(`/api/admin/received-files/${id}`,{method:'DELETE'});receivedFiles()}catch(e){alert(e.message)}}
function fmtSize(n){n=Number(n||0);return n<1024?n+' Б':n<1048576?(n/1024).toFixed(1)+' КБ':(n/1048576).toFixed(1)+' МБ'}
async function admin(){const me=await api('/api/me');role=me.role||'user';if(role!=='admin'){alert('Сервер не считает текущий аккаунт администратором. Проверьте PYSPACE_ADMIN_USER и выполните вход заново.');return}const u=await api('/api/admin/users');modal('<h2>Пользователи</h2><div class="muted small">Администратор: '+esc(me.username||'')+'</div>'+u.map(x=>`<div class="member"><span>${esc(x.username)} · ${esc(x.role)}</span><span><button class="tool-btn" onclick="setRole(${x.id},'${x.role==='admin'?'user':'admin'}')">Роль</button><button class="tool-btn" onclick="delUser(${x.id})">Удалить</button></span></div>`).join(''))}
async function setRole(id,r){await api(`/api/admin/users/${id}/role`,{method:'POST',body:JSON.stringify({role:r})});admin()}async function delUser(id){if(confirm('Удалить пользователя?')){await api(`/api/admin/users/${id}`,{method:'DELETE'});admin()}}
function out(x){$('out').textContent=x}function esc(x){return String(x).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]||c))}function escAttr(x){return esc(x).replace(/\n/g,'&#10;')}
function modal(x){const modalEl=$('modal'), bodyEl=document.querySelector('#body'); if(!modalEl||!bodyEl){console.error('PySpace modal elements missing');alert('Не удалось открыть окно интерфейса. Обновите страницу (Ctrl+F5).');return} document.body.style.overflow='hidden';document.body.classList.add('modal-open');bodyEl.innerHTML=x;modalEl.classList.remove('hidden')}function hide(){const modalEl=$('modal');if(modalEl)modalEl.classList.add('hidden');document.body.style.overflow='';document.body.classList.remove('modal-open')}
function closeSidebar(){if(window.innerWidth<=760)$('sidebar').classList.remove('open')}
let projectsCache=[];
async function downloadMenu(kind){
const ps=await api('/api/projects');projectsCache=ps;
const title=kind==='project'?'Скачать проект':'Скачать отдельный файл';
const body=ps.length?ps.map(p=>`<button class="select-card" onclick="downloadFromProject(${p.id},'${kind}')"><b>▣ ${esc(p.name)}</b><small>${esc(p.access||'')}</small></button>`).join(''):'<div class="empty-state">Проектов пока нет.</div>';
modal(`<div class="download-modal"><div class="eyebrow">DOWNLOAD</div><h2>${title}</h2><p class="muted">Выберите проект.</p><div class="select-list">${body}</div></div>`);
}
async function downloadFromProject(pid,kind){
if(kind==='project'){location.href=`/api/projects/${pid}/download.zip`;hide();return;}
const fs=await api(`/api/projects/${pid}/files`);
const body=fs.length?fs.map(f=>`<button class="select-card" onclick="downloadOne(${pid},'${escAttr(f.path)}')"><b>${fileIcon(f.language)} ${esc(f.path)}</b><small>${esc(f.language)}</small></button>`).join(''):'<div class="empty-state">В проекте нет файлов.</div>';
modal(`<div class="download-modal"><div class="eyebrow">FILE</div><h2>Выберите файл</h2><div class="select-list">${body}</div></div>`);
}
function downloadOne(pid,path){location.href=`/api/projects/${pid}/download/${path.split('/').map(encodeURIComponent).join('/')}`;hide()}
async function terminalMenu(){
const ps=await api('/api/projects');
const sel=$('terminalProject');
if(sel){sel.innerHTML=ps.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join(''); if(project)sel.value=project.id;}
$('terminalPanel').classList.remove('hidden'); $('terminalCommand').focus();
}
function closeTerminal(){$('terminalPanel').classList.add('hidden')}
function terminalOutput(t){$('terminalOutput').textContent=t||'Готово.'}
async function runTerminal(){const pid=Number($('terminalProject').value),cmd=$('terminalCommand').value.trim();if(!pid||!cmd)return;terminalOutput('▶ Выполнение...');try{const d=await api('/api/terminal',{method:'POST',body:JSON.stringify({project_id:pid,command:cmd})});terminalOutput((d.ok?'✓ ':'✕ ')+(d.output||'')+`\n[exit ${d.returncode??0}]`)}catch(e){terminalOutput('✕ '+e.message)}}
async function terminalInstall(){const pid=Number($('terminalProject').value);if(!pid)return;modal(`<div class="download-modal"><div class="eyebrow">PYTHON PACKAGES</div><h2>Установить пакет</h2><p class="muted">Пакет будет установлен только в выбранный проект.</p><input id="pipPackage" class="modal-input" placeholder="requests или requests==2.32.3" autocomplete="off"><div class="modal-actions"><button class="secondary" onclick="hide()">Отмена</button><button class="primary" onclick="installPackage(${pid})">Установить</button></div></div>`);setTimeout(()=>$('pipPackage')?.focus(),30)}
async function installPackage(pid){const pkg=$('pipPackage')?.value.trim();if(!pkg)return;hide();terminalOutput('▶ pip install '+pkg+' ...');try{const d=await api(`/api/projects/${pid}/pip-install`,{method:'POST',body:JSON.stringify({package:pkg})});terminalOutput((d.ok?'✓ ':'✕ ')+(d.output||''))}catch(e){terminalOutput('✕ '+e.message)}}
async function quickQR(){
try{
const d=await api('/api/local-share',{method:'POST'});
const url=d.share_url||d.cloud_url||(d.urls&&d.urls[0]);
if(!url||!d.token)throw new Error('Сервер не вернул ссылку обмена');
const qrUrl='/api/local-share/'+encodeURIComponent(d.token)+'/qr';
modal(`
<div class="qr-modal">
<div class="qr-kicker">QUICK SHARE</div>
<h2>Отправить файл</h2>
<p class="muted">Отсканируйте QR-код камерой телефона.</p>
<div class="qr-frame"><img src="${qrUrl}" alt="QR-код" onerror="this.parentElement.innerHTML='<div style=\"color:#c55\">Не удалось загрузить QR</div>'"></div>
<div class="qr-url">${esc(url)}</div>
<div class="qr-actions">
<button class="primary" onclick="copyText('${escAttr(url)}')">Копировать ссылку</button>
<a class="secondary" href="${qrUrl}" target="_blank" rel="noopener">Открыть QR</a>
</div>
<div class="qr-note">Ссылка короткая и ведёт прямо на страницу отправки файлов.</div>
</div>`);
}catch(e){alert('Не удалось создать QR-код: '+e.message);}
}
window.login=login;window.register=register;window.receivedFiles=receivedFiles;window.assignReceived=assignReceived;window.deleteReceived=deleteReceived;window.logout=logout;window.newProject=newProject;window.renameProject=renameProject;window.newFile=newFile;window.save=save;window.uploadFiles=uploadFiles;window.downloadCurrent=downloadCurrent;window.downloadZip=downloadZip;window.deleteFile=deleteFile;window.renameFile=renameFile;window.run=run;window.preview=preview;window.share=share;window.localShare=localShare;window.admin=admin;window.setRole=setRole;window.delUser=delUser;window.hide=hide;window.copyText=copyText;window.downloadMenu=downloadMenu;window.downloadFromProject=downloadFromProject;window.downloadOne=downloadOne;window.terminalMenu=terminalMenu;window.closeTerminal=closeTerminal;window.runTerminal=runTerminal;window.terminalInstall=terminalInstall;window.installPackage=installPackage;window.quickQR=quickQR;
window.addEventListener('DOMContentLoaded',()=>{$('terminalCommand')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();runTerminal()}});$('loginBtn').addEventListener('click',login);$('registerBtn').addEventListener('click',register);$('password').addEventListener('keydown',e=>{if(e.key==='Enter')login()});$('uploadInput').addEventListener('change',e=>{uploadFiles(e.target.files);e.target.value=''});$('langSelect').addEventListener('change',e=>setLanguage(e.target.value));$('menuBtn').addEventListener('click',()=>$('sidebar').classList.toggle('open'));initEditor()});window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save()}if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();run()}});
