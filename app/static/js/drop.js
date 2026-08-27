/** Публичная страница комнаты обмена: загрузка файлов и текста без входа. */
import { clear, el, humanSize, qs } from './core/dom.js';

const card = qs('#dropCard');
if (card) {
  const token = card.dataset.token;
  const maxMb = Number(card.dataset.max || 200);
  const zone = qs('#dropZone');
  const input = qs('#dropInput');
  const queue = qs('#dropQueue');
  const status = qs('#dropStatus');
  const sendBtn = qs('#dropSend');
  let files = [];

  const setStatus = (text, kind = '') => {
    status.textContent = text;
    status.dataset.kind = kind;
  };

  function renderQueue() {
    clear(queue);
    files.forEach((file, index) => {
      queue.append(el('li', {}, [
        el('span', { class: 'grow', text: file.name }),
        el('small', { text: humanSize(file.size) }),
        el('button', {
          type: 'button',
          title: 'Убрать',
          text: '✕',
          onClick: () => { files.splice(index, 1); renderQueue(); },
        }),
      ]));
    });
    const total = files.reduce((sum, file) => sum + file.size, 0);
    sendBtn.textContent = files.length
      ? `Отправить ${files.length} файл(ов) · ${humanSize(total)}`
      : 'Отправить';
    if (total > maxMb * 1024 * 1024) setStatus(`Слишком много: максимум ${maxMb} МБ за раз.`, 'error');
    else if (status.dataset.kind === 'error') setStatus('');
  }

  function addFiles(list) {
    [...list].forEach((file) => {
      if (!files.some((existing) => existing.name === file.name && existing.size === file.size)) files.push(file);
    });
    renderQueue();
  }

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); }
  });
  input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });

  ['dragenter', 'dragover'].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault();
    zone.dataset.over = 'true';
  }));
  ['dragleave', 'dragend'].forEach((name) => zone.addEventListener(name, () => delete zone.dataset.over));
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    delete zone.dataset.over;
    if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
  });

  document.addEventListener('paste', (event) => {
    const items = [...(event.clipboardData?.files || [])];
    if (items.length) addFiles(items);
  });

  async function refreshFiles() {
    try {
      const response = await fetch(`/api/drops/${token}`);
      const data = await response.json();
      if (!data.ok) return;
      const host = qs('#dropFiles');
      const count = qs('#dropCount');
      clear(host);
      count.textContent = String(data.files.length);
      data.files.forEach((file) => {
        host.append(el('li', {}, [
          el('a', {
            class: 'grow truncate',
            href: `/api/drops/${token}/download?path=${encodeURIComponent(file.path)}`,
            text: file.path,
          }),
          el('small', { text: file.size_human }),
        ]));
      });
    } catch { /* не критично */ }
  }

  function upload(form) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      const bar = el('i');
      const wrap = el('div', { class: 'drop__bar' }, [bar]);
      status.after(wrap);

      request.open('POST', `/api/drops/${token}/upload`);
      request.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        bar.style.right = `${100 - Math.round((event.loaded / event.total) * 100)}%`;
      };
      request.onload = () => {
        wrap.remove();
        let data = {};
        try { data = JSON.parse(request.responseText); } catch { /* нечитаемый ответ */ }
        if (request.status < 400 && data.ok) resolve(data);
        else reject(new Error(data.error || `Ошибка сервера (${request.status})`));
      };
      request.onerror = () => { wrap.remove(); reject(new Error('Не удалось связаться с сервером.')); };
      request.send(form);
    });
  }

  sendBtn.addEventListener('click', async () => {
    const text = qs('#dropText').value;
    if (!files.length && !text.trim()) { setStatus('Выберите файлы или введите текст.', 'error'); return; }

    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    if (text.trim()) form.append('text', text);

    sendBtn.disabled = true;
    setStatus('Отправляем…');
    try {
      const data = await upload(form);
      files = [];
      qs('#dropText').value = '';
      renderQueue();
      setStatus(data.message || 'Отправлено.', 'success');
      if (data.problems?.length) setStatus(`${data.message}. Не влезло: ${data.problems.join('; ')}`, 'error');
      refreshFiles();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      sendBtn.disabled = false;
    }
  });

  refreshFiles();
  setInterval(refreshFiles, 15000);
}
