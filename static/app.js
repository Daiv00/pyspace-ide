let ed=null,project=null,file=null,role='user';
const $=id=>document.getElementById(id);
const api=async(url,options={})=>{const opts={...options,credentials:'same-origin',headers:{...(options.body&&!(options.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...(options.headers||{})}};let r;try{r=await fetch(url,opts)}catch(e){throw new Error('Нет соединения с сервером: '+e.message)}const text=await r.text();let d={};try{d=text?JSON.parse(text):{}}catch(e){if(!r.ok)throw new Error('HTTP '+r.status)}if(!r.ok)throw new Error(d.error||('HTTP '+r.status));return d};

// --- UI helpers (these were missing entirely, which is why "esc is not defined"
// broke project/file loading and most sidebar/topbar buttons silently did nothing) ---
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function escAttr(s){return esc(s)}
function fmtSize(n){n=Number(n||0);return n<1024?n+' Б':n<1048576?(n/1024).toFixed(1)+' КБ':(n/1048576).toFixed(1)+' МБ'}
function modal(html){$('body').innerHTML=html;$('modal').classList.remove('hidden')}
function hide(){$('modal').classList.add('hidden');$('body').innerHTML=''}
function closeSidebar(){const s=$('sidebar');if(s)s.classList.remove('open')}
async function copyText(t){
  try{
    if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(t)}
    else{const ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove()}
    alert('✓ Ссылка скопирована')
  }catch(e){alert('Не удалось скопировать: '+e.message)}
}
function stdinPrompt(){
  return new Promise(resolve=>{
    const wrap=document.createElement('div');
    wrap.id='stdinModal';
    wrap.innerHTML=`<div class="stdin-backdrop"></div><div class="stdin-dialog"><div class="stdin-title">Программа ожидает ввод</div><div class="stdin-sub">Код использует input(), а тестовые данные пустые. Введите значения (каждое с новой строки) и запустите ещё раз.</div><textarea id="stdinPromptValue" rows="6" placeholder="Например:&#10;5&#10;10"></textarea><div class="stdin-actions"><button id="stdinCancel">Отмена</button><button id="stdinRun">Запустить</button></div></div>`;
    document.body.appendChild(wrap);
    const ta=wrap.querySelector('#stdinPromptValue');
    ta.focus();
    const cleanup=v=>{document.removeEventListener('keydown',onKey);wrap.remove();resolve(v)};
    const onKey=e=>{if(e.key==='Escape')cleanup(null);if(e.key==='Enter'&&e.ctrlKey)cleanup(ta.value)};
    document.addEventListener('keydown',onKey);
    wrap.querySelector('.stdin-backdrop').onclick=()=>cleanup(null);
    wrap.querySelector('#stdinCancel').onclick=()=>cleanup(null);
    wrap.querySelector('#stdinRun').onclick=()=>cleanup(ta.value);
  });
}
async function openProject(pid){
  const ps=await api('/api/projects');
  const p=ps.find(x=>x.id===pid);
  if(p)await selectProject(p);
}
function localShare(){return quickQR()}
async function share(){
  if(!project)return alert('Выберите проект');
  const username=(prompt('Логин пользователя, которому открыть доступ')||'').trim();
  if(!username)return;
  const role=(prompt('Роль доступа: editor или viewer','editor')||'').trim().toLowerCase();
  if(role!=='editor'&&role!=='viewer')return alert('Роль должна быть editor или viewer');
  try{
    await api(`/api/projects/${project.id}/share`,{method:'POST',body:JSON.stringify({username,role})});
    alert('✓ Доступ выдан: '+username+' ('+role+')');
  }catch(e){alert('✕ '+e.message)}
}
async function admin(){
  try{
    const users=await api('/api/admin/users');
    modal(`<h2>Администрирование</h2><div class="share-urls">${users.map(u=>`<div class="member"><span>${esc(u.username)} <small class="muted">(${esc(u.role)})</small></span><span class="qr-actions"><select data-uid="${u.id}" class="admin-role"><option value="user" ${u.role==='user'?'selected':''}>user</option><option value="admin" ${u.role==='admin'?'selected':''}>admin</option></select><button class="secondary admin-del" data-uid="${u.id}">Удалить</button></span></div>`).join('')}</div>`);
    $('body').querySelectorAll('.admin-role').forEach(sel=>sel.onchange=async()=>{
      try{await api(`/api/admin/users/${sel.dataset.uid}/role`,{method:'POST',body:JSON.stringify({role:sel.value})})}catch(e){alert('✕ '+e.message)}
    });
    $('body').querySelectorAll('.admin-del').forEach(btn=>btn.onclick=async()=>{
      if(!confirm('Удалить пользователя?'))return;
      try{await api(`/api/admin/users/${btn.dataset.uid}`,{method:'DELETE'});btn.closest('.member').remove()}catch(e){alert('✕ '+e.message)}
    });
  }catch(e){alert('✕ '+e.message)}
}
async function receivedFiles(){
  try{
    const files=await api('/api/received-files');
    const isAdmin=role==='admin';
    modal(`<h2>Переданные файлы</h2><div class="received-list">${
      files.length?files.map(f=>`<div class="received-item"><div class="received-main"><b>📄 ${esc(f.original_name)}</b><small>от ${esc(f.owner_name)}${f.recipient_name?' → '+esc(f.recipient_name):''} · ${fmtSize(f.size)}</small></div><div class="received-actions"><a class="tool-btn" href="/api/received-files/${f.id}/download">Скачать</a>${isAdmin?`<button class="tool-btn assign-btn" data-fid="${f.id}">Назначить</button><button class="tool-btn danger-text del-received" data-fid="${f.id}">Удалить</button>`:''}</div></div>`).join(''):'<div class="empty-state">Пока ничего не получено.</div>'
    }</div>`);
    $('body').querySelectorAll('.assign-btn').forEach(btn=>btn.onclick=async()=>{
      const username=(prompt('Логин получателя')||'').trim();if(!username)return;
      try{await api(`/api/admin/received-files/${btn.dataset.fid}/assign`,{method:'POST',body:JSON.stringify({username})});alert('✓ Назначено: '+username)}catch(e){alert('✕ '+e.message)}
    });
    $('body').querySelectorAll('.del-received').forEach(btn=>btn.onclick=async()=>{
      if(!confirm('Удалить файл?'))return;
      try{await api(`/api/admin/received-files/${btn.dataset.fid}`,{method:'DELETE'});btn.closest('.received-item').remove()}catch(e){alert('✕ '+e.message)}
    });
  }catch(e){alert('✕ '+e.message)}
}
function out(t){$('out').textContent=t}

function msg(t){$('msg').textContent=t?.message||String(t||'')}function setBusy(v){$('loginBtn').disabled=v;$('registerBtn').disabled=v}
async function login(){const username=$('username').value.trim(),password=$('password').value;if(!username||!password)return msg('Введите логин и пароль');setBusy(true);msg('Выполняется вход...');try{start(await api('/api/login',{method:'POST',body:JSON.stringify({username,password})}))}catch(e){msg(e)}finally{setBusy(false)}}
async function register(){const username=$('username').value.trim(),password=$('password').value;if(!username||!password)return msg('Введите логин и пароль');setBusy(true);msg('Создание аккаунта...');try{const d=await api('/api/register',{method:'POST',body:JSON.stringify({username,password})});msg(d.role==='admin'?'Аккаунт создан как admin. Теперь войдите.':'Аккаунт создан. Теперь нажмите «Войти».')}catch(e){msg(e)}finally{setBusy(false)}}
function start(m){$('auth').classList.add('hidden');$('app').classList.remove('hidden');$('who').textContent=m.username||'';role=m.role||'user';$('admin').style.display=role==='admin'?'inline-flex':'none';if(ed&&ed.isFallback)out('⚠ Редактор Monaco не загрузился (проблема с CDN). Включён упрощённый текстовый редактор: открытие/редактирование/сохранение файлов работают, но без подсветки синтаксиса.');loadProjects().catch(msg)}
async function boot(){try{const m=await api('/api/me');if(m.authenticated)start(m)}catch(e){msg(e)}}
function createFallbackEditor(){
  const host=$('editor');
  host.innerHTML='';
  const ta=document.createElement('textarea');
  ta.id='fallbackEditor';
  ta.spellcheck=false;
  ta.style.cssText='width:100%;height:100%;box-sizing:border-box;border:0;outline:none;resize:none;background:#1e1e1e;color:#d4d4d4;padding:12px;font:14px/1.5 ui-monospace,Consolas,monospace;tab-size:4;white-space:pre;overflow:auto';
  host.appendChild(ta);
  return {isFallback:true,getValue:()=>ta.value,setValue:v=>{ta.value=v??''},getModel:()=>null};
}
function initEditor(){
  if(typeof require==='undefined'){
    ed=createFallbackEditor();boot();return;
  }
  require.config({paths:{vs:'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs'}});
  require(['vs/editor/editor.main'],()=>{
    ed=monaco.editor.create($('editor'),{value:'',language:'python',theme:'vs-dark',automaticLayout:true,minimap:{enabled:false},fontSize:14,tabSize:4,wordWrap:'on',padding:{top:12,bottom:12},scrollBeyondLastLine:false});
    boot();
  },()=>{ed=createFallbackEditor();boot()});
}
async function logout(){try{await api('/api/logout',{method:'POST'})}finally{location.reload()}}
async function loadProjects(){
  const ps=await api('/api/projects');
  $('projects').innerHTML=ps.map(p=>`<div class="project ${project?.id===p.id?'active':''}" data-pid="${p.id}"><span>▸ ${esc(p.name)}</span><span class="project-right"><small>${esc(p.access)}</small>${p.access==='owner'?`<button class="project-del" data-pid="${p.id}" title="Удалить проект" aria-label="Удалить проект">🗑</button>`:''}</span></div>`).join('');
  $('projects').querySelectorAll('.project').forEach((el,i)=>el.onclick=e=>{if(e.target.closest('.project-del'))return;selectProject(ps[i])});
  $('projects').querySelectorAll('.project-del').forEach(btn=>btn.onclick=e=>{e.stopPropagation();deleteProject(Number(btn.dataset.pid),ps)});
  if(!project&&ps[0])await selectProject(ps[0])
}
async function deleteProject(pid,ps){
  const p=(ps||[]).find(x=>x.id===pid);
  if(!confirm(`Удалить проект «${p?p.name:pid}» безвозвратно? Это действие нельзя отменить.`))return;
  try{
    await api(`/api/projects/${pid}`,{method:'DELETE'});
    if(project&&project.id===pid){
      project=null;file=null;
      $('tab').textContent='';$('files').innerHTML='';
      if(ed)ed.setValue('');
      out('✓ Проект удалён.');
    }
    await loadProjects();
  }catch(e){alert('✕ Не удалось удалить проект: '+e.message)}
}
async function selectProject(p){
  try{
    project=p;file=null;await loadProjects();await loadFiles();closeSidebar();
  }catch(e){out('✕ '+e.message)}
}
async function loadFiles(){const fs=await api(`/api/projects/${project.id}/files`);$('files').innerHTML=fs.map(f=>`<div class="file ${file?.path===f.path?'active':''}"><span>${fileIcon(f.language)} ${esc(f.path)}</span></div>`).join('');$('files').querySelectorAll('.file').forEach((el,i)=>el.onclick=()=>openFile(fs[i].path));if(!file&&fs[0])await openFile(fs[0].path)}
function fileIcon(l){return ({python:'🐍',html:'◇',css:'◈',sql:'▤',javascript:'JS',json:'{}',plaintext:'·'})[l]||'·'}
async function openFile(p){
  try{
    file=await api(`/api/projects/${project.id}/files/${p.split('/').map(encodeURIComponent).join('/')}`);
    if(ed){ed.setValue(file.content);setLanguage(file.language)}
    else out('⚠ Редактор не загрузился, но файл открыт: '+file.path);
    $('tab').textContent=file.path;
    await loadFiles();
  }catch(e){
    out('✕ Не удалось открыть файл: '+e.message);
  }
}
function setLanguage(l){$('langSelect').value=l;if(ed&&!ed.isFallback){monaco.editor.setModelLanguage(ed.getModel(),l)}}
async function newProject(){
  let n=prompt('Название проекта');if(!n)return;
  try{
    project=await api('/api/projects',{method:'POST',body:JSON.stringify({name:n})});
    file=null;await loadProjects();await loadFiles();
  }catch(e){alert('✕ Не удалось создать проект: '+e.message)}
}
async function newFile(){
  if(!project)return alert('Выберите проект');
  let p=prompt('Путь, например src/utils.py');if(!p)return;
  try{
    await api(`/api/projects/${project.id}/files`,{method:'POST',body:JSON.stringify({path:p,content:''})});
    await openFile(p);
  }catch(e){alert('✕ Не удалось создать файл: '+e.message)}
}
async function save(){
  if(!project||!file||!ed)return;
  try{
    await api(`/api/projects/${project.id}/files`,{method:'POST',body:JSON.stringify({path:file.path,content:ed.getValue()})});
    out('✓ Сохранено: '+file.path);
  }catch(e){
    out('✕ Не удалось сохранить: '+e.message);
    throw e;
  }
}
async function uploadFiles(list){
  if(!list.length)return;
  if(!project)return alert('Сначала выберите или создайте проект слева.');
  const fd=new FormData();[...list].forEach(f=>fd.append('files',f));
  try{
    const r=await api(`/api/projects/${project.id}/upload`,{method:'POST',body:fd});
    if(!r.files||!r.files.length)return alert('Файл не загрузился. Проверьте, что выбран файл, и попробуйте ещё раз.');
    out('✓ Загружено:\n'+r.files.join('\n'));await loadFiles();if(r.files[0])await openFile(r.files[0])
  }catch(e){alert('✕ Не удалось загрузить файл: '+e.message);out('✕ '+e.message)}
}
async function pasteFromClipboard(){
  if(!ed)return alert('Редактор ещё не загрузился.');
  if(!project||!file)return alert('Сначала откройте файл, куда вставлять код.');
  let text;
  try{
    text=await navigator.clipboard.readText();
  }catch(e){
    return alert('Нет доступа к буферу обмена.\nРазрешите доступ к буферу обмена для этого сайта: значок замка рядом с адресом сайта → «Разрешения» → «Буфер обмена» → Разрешить, затем попробуйте снова.');
  }
  if(!text)return alert('Буфер обмена пуст. Сначала скопируйте код в другом приложении.');
  if(ed.isFallback){
    const ta=document.getElementById('fallbackEditor');
    const start=ta.selectionStart??ta.value.length,end=ta.selectionEnd??ta.value.length;
    ta.value=ta.value.slice(0,start)+text+ta.value.slice(end);
    const pos=start+text.length;ta.selectionStart=ta.selectionEnd=pos;ta.focus();
  }else{
    const sel=ed.getSelection();
    ed.executeEdits('manual-paste',[{range:sel,text,forceMoveMarkers:true}]);
    ed.focus();
  }
  out('✓ Вставлено из буфера обмена: '+text.length+' симв.');
}
async function downloadCurrent(){if(!project||!file)return;location.href=`/api/projects/${project.id}/download/${file.path.split('/').map(encodeURIComponent).join('/')}`}
async function downloadZip(){if(!project)return;location.href=`/api/projects/${project.id}/download.zip`}
async function formatCode(){
  if(!project||!file)return;
  if(!ed)return out('✕ Редактор не загрузился, форматирование недоступно.');
  const language=file.language||$('langSelect').value;
  if(!['python','html','css','javascript','json'].includes(language))return out('Форматирование доступно для Python, HTML, CSS, JS, JSON.');
  try{
    out('🧹 Форматирование...');
    const d=await api(`/api/projects/${project.id}/format`,{method:'POST',body:JSON.stringify({content:ed.getValue(),language})});
    ed.setValue(d.content);
    await save();
    out('✓ Отформатировано и сохранено: '+file.path);
  }catch(e){
    out('✕ Не удалось отформатировать: '+e.message);
  }
}
async function deleteFile(){
  if(!file||!confirm('Удалить файл?'))return;
  try{
    await api(`/api/projects/${project.id}/files`,{method:'DELETE',body:JSON.stringify({path:file.path})});
    file=null;await loadFiles();
  }catch(e){alert('✕ Не удалось удалить файл: '+e.message)}
}
async function renameFile(){
  if(!file)return;
  let p=prompt('Новый путь',file.path);if(!p||p===file.path)return;
  try{
    await api(`/api/projects/${project.id}/rename`,{method:'POST',body:JSON.stringify({old_path:file.path,new_path:p})});
    await openFile(p);
  }catch(e){alert('✕ Не удалось переименовать файл: '+e.message)}
}
async function run(stdinOverride){
  if(!project||!file)return;
  if(!ed)return out('✕ Редактор не загрузился (проблема с CDN Monaco). Обновите страницу — если не помогает, используйте резервный текстовый редактор, который включается автоматически.');
  try{
    await save();
    let stdin=stdinOverride===undefined?$('stdin').value:stdinOverride;
    const code=ed.getValue();
    if(stdinOverride===undefined && /\binput\s*\(/.test(code) && !stdin.trim()){
      const entered=await stdinPrompt();if(entered===null)return;
      stdin=entered;$('stdin').value=entered;
    }
    out('▶ Выполнение...');
    const d=await api('/api/run',{method:'POST',body:JSON.stringify({project_id:project.id,path:file.path,stdin})});
    out((d.ok?'✓ Успешно\n\n':'✕ Ошибка\n\n')+(d.output||d.error||''));
    if(d.kind==='html'||d.kind==='css')preview();
    if(d.kind==='web'&&d.ok&&d.url)webPreview(d.url,d.token);
    if(d.kind==='web'&&!d.ok)out('✕ Ошибка запуска веб-приложения\n\n'+(d.error||d.output||''));
  }catch(e){
    out('✕ '+e.message);
  }
}
function webPreview(url,token){modal(`<div class="web-preview-head"><div><div class="eyebrow">LIVE WEB APP</div><h2>Веб-приложение</h2><p class="muted">Работает прямо внутри PySpace. Никакого отдельного Deploy не требуется.</p></div><div style="display:flex;gap:6px"><a class="tool-btn" href="${escAttr(url)}" target="_blank" rel="noopener">Открыть отдельно ↗</a>${token?`<button class="tool-btn danger" onclick="stopWebPreview('${escAttr(token)}')">Остановить</button>`:''}</div></div><iframe class="preview web-live-preview" src="${escAttr(url)}" sandbox="allow-scripts allow-forms allow-same-origin"></iframe>`)}
async function stopWebPreview(token){
  try{await api(`/api/web-preview/${encodeURIComponent(token)}/stop`,{method:'POST'});hide();out('■ Веб-приложение остановлено')}catch(e){alert('✕ '+e.message)}
}
async function preview(){
 if(!project||!file)return;
 const ext=file.path.toLowerCase().split('.').pop();
 if(!['html','htm','css'].includes(ext))return out('Предпросмотр доступен для HTML/CSS.');
 try{
   await save();
   if(ext==='html'||ext==='htm'){
     const url=`/api/projects/${project.id}/preview/${file.path.split('/').map(encodeURIComponent).join('/')}`;
     modal(`<div class="web-preview-head"><div><div class="eyebrow">HTML PREVIEW</div><h2>${esc(file.path)}</h2></div><a class="tool-btn" href="${escAttr(url)}" target="_blank" rel="noopener">Открыть отдельно ↗</a></div><iframe class="preview web-live-preview" src="${escAttr(url)}"></iframe>`);
     return;
   }
   const html=`<!doctype html><html><head><meta charset="utf-8"><style>${ed?ed.getValue():''}</style></head><body><div class="preview-demo"><h1>PySpace CSS Preview</h1><p>Это предпросмотр CSS.</p><button>Button</button></div></body></html>`;
   modal(`<h2>Предпросмотр CSS</h2><iframe class="preview web-live-preview" srcdoc="${escAttr(html)}"></iframe>`);
 }catch(e){
   out('✕ Не удалось открыть предпросмотр: '+e.message);
 }
}
const stdinStyle=document.createElement("style");
stdinStyle.textContent=`#stdinModal{position:fixed;inset:0;z-index:99999;display:grid;place-items:center}.stdin-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.76);backdrop-filter:blur(6px)}.stdin-dialog{position:relative;width:min(560px,calc(100vw - 24px));box-sizing:border-box;background:#151a25;border:1px solid #343c4e;border-radius:18px;padding:20px;box-shadow:0 25px 90px rgba(0,0,0,.6);color:#f4f6fb}.stdin-title{font-size:20px;font-weight:750;margin-bottom:7px}.stdin-sub{font-size:13px;color:#aeb7c8;line-height:1.45;margin-bottom:14px}#stdinPromptValue{width:100%;box-sizing:border-box;background:#0b1018;color:#f4f6fb;border:1px solid #3a4355;border-radius:12px;padding:12px;font:14px ui-monospace,Consolas,monospace;resize:vertical}.stdin-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:14px}.stdin-actions button{border:0;border-radius:10px;padding:10px 16px;cursor:pointer;background:#2b3342;color:#fff}.stdin-actions #stdinRun{background:#705df5}`;
document.head.appendChild(stdinStyle);

async function quickQR(){
  try{
    const d=await api('/api/local-share',{method:'POST'});
    const url=d.share_url||d.cloud_url||(d.urls&&d.urls[0]);
    if(!url || !d.token) throw new Error('Сервер не вернул ссылку обмена');
    const qrUrl='/api/local-share/'+encodeURIComponent(d.token)+'/qr';
    modal(`
      <div class="qr-modal">
        <div class="qr-kicker">QUICK SHARE</div>
        <h2>Отправить файл</h2>
        <p class="muted">Отсканируйте QR-код камерой телефона.</p>
        <div class="qr-frame"><img src="${qrUrl}" alt="QR-код" onerror="this.parentElement.innerHTML='<div style="color:#c55">Не удалось загрузить QR</div>'"></div>
        <div class="qr-url">${esc(url)}</div>
        <div class="qr-actions">
          <button class="primary" onclick="copyText('${escAttr(url)}')">Копировать ссылку</button>
          <a class="secondary" href="${qrUrl}" target="_blank" rel="noopener">Открыть QR</a>
        </div>
        <div class="qr-note">Ссылка короткая и ведёт прямо на страницу отправки файлов.</div>
      </div>`);
  }catch(e){
    alert('Не удалось создать QR-код: '+e.message);
  }
}


document.addEventListener('DOMContentLoaded',()=>{
  const loginBtn=document.getElementById('loginBtn');
  const registerBtn=document.getElementById('registerBtn');
  if(loginBtn) loginBtn.addEventListener('click', login);
  if(registerBtn) registerBtn.addEventListener('click', register);
  const password=document.getElementById('password');
  if(password) password.addEventListener('keydown', e=>{if(e.key==='Enter') login()});

  const menuBtn=document.getElementById('menuBtn');
  if(menuBtn) menuBtn.addEventListener('click', ()=>$('sidebar').classList.toggle('open'));

  const uploadInput=document.getElementById('uploadInput');
  const uploadTrigger=document.getElementById('uploadTrigger');
  if(uploadTrigger&&uploadInput) uploadTrigger.addEventListener('click', ()=>uploadInput.click());
  if(uploadInput) uploadInput.addEventListener('change', async e=>{await uploadFiles(e.target.files);e.target.value=''});

  const modalEl=document.getElementById('modal');
  if(modalEl) modalEl.addEventListener('click', e=>{if(e.target===modalEl) hide()});

  const langSelect=document.getElementById('langSelect');
  if(langSelect) langSelect.addEventListener('change', e=>{if(ed&&!ed.isFallback) monaco.editor.setModelLanguage(ed.getModel(), e.target.value)});

  initEditor();
});
