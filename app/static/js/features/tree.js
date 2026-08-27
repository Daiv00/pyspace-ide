/** Дерево файлов и папок: отрисовка, контекстное меню, перетаскивание, загрузка. */
import api from '../core/api.js';
import { clear, el, humanSize, pickFiles, qs } from '../core/dom.js';
import { confirmSheet, promptSheet, showMenu } from '../core/modal.js';
import { canWrite, emit, state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as tabs from './tabs.js';

const parentOf = (path) => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '');
const join = (dir, name) => (dir ? `${dir}/${name}` : name);

/** Собирает иерархию из плоского списка узлов. */
function buildTree(nodes) {
  const dirs = new Map([['', { path: '', type: 'dir', children: [] }]]);
  const ensure = (path) => {
    if (dirs.has(path)) return dirs.get(path);
    const node = { path, name: path.split('/').pop(), type: 'dir', children: [] };
    dirs.set(path, node);
    ensure(parentOf(path)).children.push(node);
    return node;
  };
  for (const node of nodes) {
    if (node.type === 'dir') ensure(node.path);
    else ensure(parentOf(node.path)).children.push({ ...node, children: null });
  }
  const sort = (node) => {
    if (!node.children) return;
    node.children.sort((a, b) => {
      if ((a.type === 'dir') !== (b.type === 'dir')) return a.type === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name, 'ru');
    });
    node.children.forEach(sort);
  };
  const root = dirs.get('');
  sort(root);
  return root;
}

export async function refresh() {
  if (!state.project) return;
  try {
    const { tree } = await api.tree(state.project.id);
    state.tree = tree;
    render();
    emit('tree:loaded', tree);
  } catch (error) {
    notify.error(error.message || 'Не удалось получить список файлов.');
  }
}

export function render() {
  const host = qs('#tree');
  if (!host) return;
  clear(host);
  const root = buildTree(state.tree || []);
  if (!root.children.length) {
    host.append(el('div', { class: 'empty' }, [
      el('strong', { text: 'Проект пуст' }),
      'Создайте файл или перетащите папку сюда.',
    ]));
    return;
  }
  root.children.forEach((node) => host.append(renderNode(node, 0)));
}

function renderNode(node, depth) {
  const isDir = node.type === 'dir';
  const open = state.openFolders.has(node.path);
  const row = el('div', {
    class: 'tree-node',
    role: 'treeitem',
    tabindex: '0',
    title: node.path,
    draggable: 'true',
    'aria-selected': state.selectedPath === node.path ? 'true' : 'false',
    dataset: { path: node.path, type: node.type, open: open ? 'true' : 'false' },
    style: { paddingLeft: `${6 + depth * 13}px` },
  }, [
    el('span', { class: 'tree-node__twist', text: isDir ? '▶' : '' }),
    el('span', { class: 'tree-node__icon', text: isDir ? (open ? '📂' : '📁') : tabs.fileIcon(node.name) }),
    el('span', { class: 'tree-node__name', text: node.name }),
    !isDir && node.size !== undefined
      ? el('span', { class: 'tree-node__meta', text: humanSize(node.size) })
      : null,
  ]);

  row.addEventListener('click', () => {
    state.selectedPath = node.path;
    if (isDir) toggle(node.path);
    else tabs.open(node.path);
    markSelection();
  });
  row.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); row.click(); }
    else if (event.key === 'F2') { event.preventDefault(); rename(node); }
    else if (event.key === 'Delete') { event.preventDefault(); remove(node); }
  });
  row.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    state.selectedPath = node.path;
    markSelection();
    nodeMenu(event, node);
  });
  attachDrag(row, node);

  if (!isDir) return row;

  const children = el('div', { class: 'tree-children' }, node.children.map((child) => renderNode(child, depth + 1)));
  children.hidden = !open;
  return el('div', {}, [row, children]);
}

function markSelection() {
  document.querySelectorAll('#tree .tree-node').forEach((node) => {
    node.setAttribute('aria-selected', node.dataset.path === state.selectedPath ? 'true' : 'false');
  });
}

export function toggle(path) {
  if (state.openFolders.has(path)) state.openFolders.delete(path);
  else state.openFolders.add(path);
  render();
}

export function reveal(path) {
  const parts = String(path).split('/');
  parts.pop();
  let current = '';
  for (const part of parts) {
    current = join(current, part);
    state.openFolders.add(current);
  }
  state.selectedPath = path;
  render();
  document.querySelector(`#tree .tree-node[data-path="${CSS.escape(path)}"]`)
    ?.scrollIntoView({ block: 'nearest' });
}

/* -------------------------------------------------------- операции с узлами */

/** Папка, в которую логично класть новые файлы. */
export function targetDir() {
  const selected = state.selectedPath;
  if (!selected) return '';
  const node = (state.tree || []).find((item) => item.path === selected);
  if (node && node.type === 'dir') return selected;
  return parentOf(selected);
}

export async function createFile(dir = targetDir()) {
  if (!requireWrite()) return;
  const name = await promptSheet({
    title: 'Новый файл',
    label: dir ? `Имя файла в папке «${dir}»` : 'Имя файла',
    placeholder: 'script.py',
  });
  if (!name) return;
  const path = join(dir, name);
  try {
    const result = await api.createEntry(state.project.id, path, 'file');
    await refresh();
    reveal(result.path || path);
    await tabs.open(result.path || path);
  } catch (error) {
    notify.error(error.message);
  }
}

export async function createFolder(dir = targetDir()) {
  if (!requireWrite()) return;
  const name = await promptSheet({
    title: 'Новая папка',
    label: dir ? `Имя папки внутри «${dir}»` : 'Имя папки',
    placeholder: 'src',
  });
  if (!name) return;
  try {
    const result = await api.createEntry(state.project.id, join(dir, name), 'dir');
    state.openFolders.add(result.path || join(dir, name));
    await refresh();
  } catch (error) {
    notify.error(error.message);
  }
}

export async function rename(node) {
  if (!requireWrite()) return;
  const name = await promptSheet({
    title: 'Переименовать',
    label: 'Новое имя',
    value: node.name,
    confirmText: 'Переименовать',
  });
  if (!name || name === node.name) return;
  const to = join(parentOf(node.path), name);
  try {
    const result = await api.moveEntry(state.project.id, node.path, to);
    tabs.renamePath(node.path, result.path || to);
    await refresh();
  } catch (error) {
    notify.error(error.message);
  }
}

export async function remove(node) {
  if (!requireWrite()) return;
  const yes = await confirmSheet({
    title: node.type === 'dir' ? 'Удалить папку?' : 'Удалить файл?',
    message: `«${node.path}» будет удалён безвозвратно.`,
    confirmText: 'Удалить',
    danger: true,
  });
  if (!yes) return;
  try {
    await api.deleteEntry(state.project.id, node.path);
    tabs.dropPath(node.path);
    await refresh();
    notify.ok('Удалено.');
  } catch (error) {
    notify.error(error.message);
  }
}

async function duplicate(node) {
  if (!requireWrite()) return;
  const dot = node.name.lastIndexOf('.');
  const copyName = dot > 0
    ? `${node.name.slice(0, dot)}-копия${node.name.slice(dot)}`
    : `${node.name}-копия`;
  try {
    await api.copyEntry(state.project.id, node.path, join(parentOf(node.path), copyName));
    await refresh();
  } catch (error) {
    notify.error(error.message);
  }
}

function requireWrite() {
  if (!state.project) { notify.warn('Сначала выберите проект.'); return false; }
  if (!canWrite()) { notify.warn('У вас доступ только для чтения.'); return false; }
  return true;
}

function nodeMenu(event, node) {
  const isDir = node.type === 'dir';
  showMenu([
    { heading: node.path },
    !isDir ? { label: 'Открыть', icon: '↗', onSelect: () => tabs.open(node.path) } : null,
    isDir ? { label: 'Новый файл здесь', icon: '＋', onSelect: () => createFile(node.path) } : null,
    isDir ? { label: 'Новая папка здесь', icon: '📁', onSelect: () => createFolder(node.path) } : null,
    isDir ? { label: 'Загрузить файлы сюда', icon: '⇧', onSelect: () => uploadInto(node.path) } : null,
    { separator: true },
    { label: 'Переименовать', icon: '✎', hint: 'F2', onSelect: () => rename(node) },
    { label: 'Дублировать', icon: '⧉', onSelect: () => duplicate(node) },
    {
      label: isDir ? 'Скачать папку (ZIP)' : 'Скачать файл',
      icon: '⤓',
      onSelect: async () => {
        const { downloadUrl } = await import('../core/dom.js');
        downloadUrl(`/api/projects/${state.project.id}/download?path=${encodeURIComponent(node.path)}`, node.name);
      },
    },
    {
      label: 'Копировать путь',
      onSelect: async () => {
        const { copyText } = await import('../core/dom.js');
        await copyText(node.path);
        notify.ok('Путь скопирован.');
      },
    },
    { separator: true },
    { label: 'Удалить', icon: '🗑', danger: true, hint: 'Del', onSelect: () => remove(node) },
  ].filter(Boolean), { x: event.clientX, y: event.clientY });
}

/* --------------------------------------------------------------- загрузка -- */

export async function uploadInto(dir = targetDir()) {
  if (!requireWrite()) return;
  const files = await pickFiles({ multiple: true });
  if (files.length) await sendFiles(files, dir);
}

export async function sendFiles(files, dir = '') {
  if (!requireWrite()) return;
  const form = new FormData();
  form.append('target', dir || '');
  let bytes = 0;
  for (const file of files) {
    bytes += file.size;
    form.append('files', file, file.webkitRelativePath || file.name);
  }
  const limit = state.limits.max_upload_mb * 1024 * 1024;
  if (bytes > limit) {
    notify.error(`Слишком много данных: ${humanSize(bytes)}. Лимит запроса — ${state.limits.max_upload_mb} МБ.`);
    return;
  }
  const pending = notify.info(`Загрузка (${humanSize(bytes)})…`);
  try {
    const result = await api.uploadFiles(state.project.id, form);
    notify.ok(result.message || 'Файлы загружены.');
    await refresh();
  } catch (error) {
    notify.error(error.message);
  } finally {
    pending?.remove();
  }
}

/** Перетаскивание файлов из системы в проводник. */
export function enableDropzone() {
  const zone = qs('#treePanelBody');
  const hint = qs('#treeDropzone');
  if (!zone) return;

  const setDrag = (on) => { if (hint) hint.dataset.drag = on ? 'true' : 'false'; };

  ['dragenter', 'dragover'].forEach((name) => {
    zone.addEventListener(name, (event) => {
      if (!event.dataTransfer?.types.includes('Files')) return;
      event.preventDefault();
      setDrag(true);
    });
  });
  zone.addEventListener('dragleave', (event) => {
    if (event.relatedTarget && zone.contains(event.relatedTarget)) return;
    setDrag(false);
  });
  zone.addEventListener('drop', async (event) => {
    if (!event.dataTransfer?.files?.length) return;
    event.preventDefault();
    setDrag(false);
    const target = event.target.closest('.tree-node');
    const dir = target
      ? (target.dataset.type === 'dir' ? target.dataset.path : parentOf(target.dataset.path))
      : '';
    await sendFiles(Array.from(event.dataTransfer.files), dir);
  });
}

/** Перемещение узлов внутри дерева мышью. */
function attachDrag(row, node) {
  row.addEventListener('dragstart', (event) => {
    event.dataTransfer.setData('application/x-pyspace-path', node.path);
    event.dataTransfer.effectAllowed = 'move';
  });
  row.addEventListener('dragover', (event) => {
    const source = event.dataTransfer.types.includes('application/x-pyspace-path');
    if (!source || node.type !== 'dir') return;
    event.preventDefault();
    row.dataset.drop = 'true';
  });
  row.addEventListener('dragleave', () => { delete row.dataset.drop; });
  row.addEventListener('drop', async (event) => {
    delete row.dataset.drop;
    const from = event.dataTransfer.getData('application/x-pyspace-path');
    if (!from || node.type !== 'dir') return;
    event.preventDefault();
    if (from === node.path || node.path.startsWith(`${from}/`)) return;
    const to = join(node.path, from.split('/').pop());
    if (to === from) return;
    try {
      const result = await api.moveEntry(state.project.id, from, to);
      tabs.renamePath(from, result.path || to);
      state.openFolders.add(node.path);
      await refresh();
    } catch (error) {
      notify.error(error.message);
    }
  });
}
