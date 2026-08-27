/** Живой предпросмотр веб-проекта в изолированном iframe. */
import { qs } from '../core/dom.js';
import { on, prefs, state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as editor from './editor.js';

let currentPath = '';
let watchTimer = null;
let lastStamp = 0;
let mobile = false;

const baseUrl = () => (state.project ? `/preview/${state.project.preview_token}` : '');

function urlFor(path) {
  const clean = String(path || '').replace(/^\/+/, '');
  return `${baseUrl()}/${clean}`;
}

export function isOpen() {
  return qs('#editorArea')?.dataset.preview === 'true';
}

/** Открыть предпросмотр; без пути — ищем index.html или первый html. */
export function open(path = '') {
  if (!state.project) return;
  if (!state.features.preview) { notify.warn('Предпросмотр отключён администратором.'); return; }

  let target = path;
  if (!target) {
    const html = (state.tree || []).filter((node) => node.type === 'file' && /\.html?$/i.test(node.path));
    const index = html.find((node) => node.path === 'index.html') || html[0];
    target = index ? index.path : '';
  }
  if (/\.css$/i.test(target) || /\.js$/i.test(target)) {
    const html = (state.tree || []).find((node) => /\.html?$/i.test(node.path));
    if (html) target = html.path;
  }

  currentPath = target;
  const area = qs('#editorArea');
  if (area) area.dataset.preview = 'true';
  state.previewOpen = true;
  prefs.set('previewOpen', true);
  reload();
  startWatch();
  setTimeout(() => editor.layout(), 80);
}

export function close() {
  const area = qs('#editorArea');
  if (area) area.dataset.preview = 'false';
  state.previewOpen = false;
  prefs.set('previewOpen', false);
  stopWatch();
  const frame = qs('#previewFrame');
  if (frame) frame.src = 'about:blank';
  setTimeout(() => editor.layout(), 80);
}

export function toggle(path = '') {
  if (isOpen()) close();
  else open(path);
}

export function reload() {
  const frame = qs('#previewFrame');
  if (!frame || !state.project) return;
  const url = `${urlFor(currentPath)}${currentPath.includes('?') ? '&' : '?'}_=${Date.now()}`;
  frame.src = url;
  const label = qs('#previewUrl');
  if (label) label.textContent = urlFor(currentPath);
}

function startWatch() {
  stopWatch();
  watchTimer = setInterval(async () => {
    if (!isOpen() || !state.project || document.hidden) return;
    try {
      const response = await fetch(`${baseUrl()}/__meta`, { credentials: 'same-origin' });
      if (!response.ok) return;
      const meta = await response.json();
      if (lastStamp && meta.updated_at > lastStamp) reload();
      lastStamp = meta.updated_at;
    } catch { /* сеть моргнула — попробуем в следующий раз */ }
  }, 2500);
}

function stopWatch() {
  clearInterval(watchTimer);
  watchTimer = null;
}

export function init() {
  qs('#previewReload')?.addEventListener('click', reload);
  qs('#previewClose')?.addEventListener('click', close);
  qs('#previewOpen')?.addEventListener('click', () => {
    if (state.project) window.open(urlFor(currentPath), '_blank', 'noopener');
  });
  qs('#previewDevice')?.addEventListener('click', () => {
    mobile = !mobile;
    const frame = qs('#previewFrame');
    if (frame) frame.dataset.device = mobile ? 'mobile' : 'desktop';
    const button = qs('#previewDevice');
    if (button) { button.textContent = mobile ? '▯' : '▭'; button.title = mobile ? 'Обычный вид' : 'Мобильный вид'; }
  });

  // Сохранение файла — мгновенное обновление, не дожидаясь опроса.
  on('file:saved', (tab) => {
    if (!isOpen()) return;
    if (/\.(html?|css|js|mjs|png|jpe?g|svg|gif|webp|json)$/i.test(tab.path)) reload();
  });
  on('project:selected', () => {
    lastStamp = 0;
    currentPath = '';
    if (isOpen()) open();
  });
}
