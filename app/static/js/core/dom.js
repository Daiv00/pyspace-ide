/** Минимальные помощники для работы с DOM. */

export const qs = (selector, root = document) => root.querySelector(selector);
export const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, value === true ? '' : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function icon(name, size = 16) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

export function clear(node) {
  while (node && node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function show(node, visible = true) {
  if (node) node.hidden = !visible;
}

export const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));

/** Человеческий размер файла. */
export function humanSize(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} Б`;
  const units = ['КБ', 'МБ', 'ГБ'];
  let size = value / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size < 10 ? size.toFixed(1) : Math.round(size)} ${units[index]}`;
}

/** Дата в человеческом виде (принимает ISO-строку из SQLite, считая её UTC). */
export function humanDate(value) {
  if (!value) return '—';
  const iso = String(value).includes('T') ? value : `${String(value).replace(' ', 'T')}Z`;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function debounce(fn, delay = 250) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

/** Копирование в буфер обмена с запасным вариантом для http-соединений. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = el('textarea', { style: { position: 'fixed', opacity: '0' } });
    area.value = text;
    document.body.append(area);
    area.select();
    const done = document.execCommand('copy');
    area.remove();
    return done;
  }
}

/** Скачивание по ссылке (используем для ZIP и файлов из хранилища). */
export function downloadUrl(url, filename) {
  const link = el('a', { href: url, download: filename || '' });
  document.body.append(link);
  link.click();
  link.remove();
}

/** Диалог выбора файлов без постоянного input в разметке. */
export function pickFiles({ multiple = true, accept = '', directory = false } = {}) {
  return new Promise((resolve) => {
    const input = el('input', { type: 'file', style: { display: 'none' } });
    if (multiple) input.multiple = true;
    if (accept) input.accept = accept;
    if (directory) { input.webkitdirectory = true; input.directory = true; }
    input.addEventListener('change', () => {
      resolve(Array.from(input.files || []));
      input.remove();
    });
    document.body.append(input);
    input.click();
  });
}
