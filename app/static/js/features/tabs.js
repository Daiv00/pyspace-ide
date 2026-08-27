/** Вкладки открытых файлов. */
import api, { ApiError } from '../core/api.js';
import { clear, el, humanSize, qs } from '../core/dom.js';
import { confirmSheet, showMenu } from '../core/modal.js';
import { emit, on, prefs, state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as editor from './editor.js';

const ICONS = {
  py: '🐍', sql: '🗄', html: '🌐', htm: '🌐', css: '🎨', js: '⚡', mjs: '⚡', ts: '⚡',
  json: '{}', md: '📝', txt: '📄', yml: '⚙', yaml: '⚙', toml: '⚙', csv: '📊',
  png: '🖼', jpg: '🖼', jpeg: '🖼', gif: '🖼', svg: '🖼', ico: '🖼', pdf: '📕', zip: '📦',
  sh: '▮', env: '🔑', gitignore: '🚫',
};

export function fileIcon(name) {
  const parts = String(name).split('.');
  const ext = parts.length > 1 ? parts.pop().toLowerCase() : '';
  return ICONS[ext] || '📄';
}

const baseName = (path) => String(path).split('/').pop();

export function find(path) {
  return state.tabs.find((tab) => tab.path === path);
}

/** Открыть файл во вкладке (и загрузить содержимое, если нужно). */
export async function open(path, { line = null, focus = true } = {}) {
  if (!state.project) return;
  let tab = find(path);
  if (!tab) {
    try {
      const { file } = await api.readFile(state.project.id, path);
      if (file.binary) {
        notify.warn(`«${baseName(path)}» — двоичный файл (${humanSize(file.size)}). Скачайте его для просмотра.`);
        return;
      }
      tab = {
        path: file.path,
        name: baseName(file.path),
        language: file.language,
        saved: file.content,
        dirty: false,
        size: file.size,
      };
      state.tabs.push(tab);
    } catch (error) {
      notify.error(error instanceof ApiError ? error.message : 'Не удалось открыть файл.');
      return;
    }
  }
  state.activePath = tab.path;
  state.selectedPath = tab.path;
  editor.show(tab.path, tab.dirty ? undefined : tab.saved, tab.language);
  if (line) editor.goTo(line);
  render();
  emit('tabs:activated', tab);
  persist();
  if (focus) editor.instance()?.focus();
}

export function activate(path) {
  const tab = find(path);
  if (!tab) return;
  state.activePath = path;
  state.selectedPath = path;
  editor.show(path, undefined, tab.language);
  render();
  emit('tabs:activated', tab);
  persist();
}

export async function close(path, { force = false } = {}) {
  const tab = find(path);
  if (!tab) return true;
  if (tab.dirty && !force) {
    const keep = await confirmSheet({
      title: 'Закрыть без сохранения?',
      message: `В файле «${tab.name}» есть несохранённые изменения. Они будут потеряны.`,
      confirmText: 'Закрыть без сохранения',
      danger: true,
    });
    if (!keep) return false;
  }
  const index = state.tabs.indexOf(tab);
  state.tabs.splice(index, 1);
  editor.dispose(path);

  if (state.activePath === path) {
    const next = state.tabs[index] || state.tabs[index - 1] || null;
    state.activePath = next ? next.path : null;
    if (next) editor.show(next.path, undefined, next.language);
    else editor.detachModel();
    emit('tabs:activated', next);
  }
  render();
  persist();
  return true;
}

export async function closeOthers(keepPath) {
  for (const tab of [...state.tabs]) {
    if (tab.path !== keepPath) await close(tab.path);
  }
}

export function closeAll() {
  state.tabs = [];
  state.activePath = null;
  editor.disposeAll();
  render();
  persist();
}

/** Сохранить активную вкладку (или указанную). */
export async function save(path = state.activePath, { silent = false } = {}) {
  const tab = find(path);
  if (!tab || !state.project) return false;
  if (state.project.access === 'viewer') {
    notify.warn('У вас доступ только для чтения.');
    return false;
  }
  const content = path === state.activePath ? editor.value() : tab.saved;
  try {
    const result = await api.saveFile(state.project.id, tab.path, content);
    tab.saved = content;
    tab.dirty = false;
    tab.size = result.size ?? tab.size;
    render();
    emit('file:saved', tab);
    if (!silent) notify.ok(`Сохранено: ${tab.name}`);
    return true;
  } catch (error) {
    notify.error(error.message || 'Не удалось сохранить файл.');
    return false;
  }
}

export async function saveAll() {
  const dirty = state.tabs.filter((tab) => tab.dirty);
  for (const tab of dirty) await save(tab.path, { silent: true });
  if (dirty.length) notify.ok(`Сохранено файлов: ${dirty.length}`);
}

/** Переименование/удаление файла снаружи — синхронизируем вкладки. */
export function renamePath(from, to) {
  for (const tab of state.tabs) {
    if (tab.path === from || tab.path.startsWith(`${from}/`)) {
      const next = to + tab.path.slice(from.length);
      editor.dispose(tab.path);
      tab.path = next;
      tab.name = baseName(next);
      if (state.activePath === from) state.activePath = next;
    }
  }
  const active = find(state.activePath);
  if (active) editor.show(active.path, active.dirty ? undefined : active.saved, active.language);
  render();
  persist();
}

export function dropPath(path) {
  const affected = state.tabs.filter((tab) => tab.path === path || tab.path.startsWith(`${path}/`));
  affected.forEach((tab) => close(tab.path, { force: true }));
}

export const dirtyCount = () => state.tabs.filter((tab) => tab.dirty).length;

/* ----------------------------------------------------------- отрисовка ---- */

export function render() {
  const host = qs('#tabs');
  if (!host) return;
  clear(host);

  state.tabs.forEach((tab) => {
    const node = el('div', {
      class: 'tab',
      role: 'tab',
      'aria-selected': tab.path === state.activePath ? 'true' : 'false',
      title: tab.path,
      draggable: 'true',
      dataset: { path: tab.path },
      onClick: (event) => { if (!event.target.closest('.tab__close')) activate(tab.path); },
      onAuxClick: (event) => { if (event.button === 1) { event.preventDefault(); close(tab.path); } },
      onContextMenu: (event) => { event.preventDefault(); tabMenu(event, tab); },
    }, [
      el('span', { class: 'tab__icon', text: fileIcon(tab.name) }),
      el('span', { class: 'tab__name', text: tab.name }),
      tab.dirty ? el('span', { class: 'tab__dirty', title: 'Не сохранено' }) : null,
      el('button', { class: 'tab__close', title: 'Закрыть', text: '✕', onClick: () => close(tab.path) }),
    ]);
    host.append(node);
  });

  enableReorder(host);

  const active = find(state.activePath);
  const statusFile = qs('#statusFile');
  if (statusFile) statusFile.textContent = active ? active.path : '—';
  const statusLang = qs('#statusLang');
  if (statusLang) statusLang.textContent = active ? active.language : '—';
  const placeholder = qs('#editorPlaceholder');
  if (placeholder) placeholder.hidden = Boolean(active);

  host.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function enableReorder(host) {
  let dragged = null;
  host.addEventListener('dragstart', (event) => {
    const tab = event.target.closest('.tab');
    if (!tab) return;
    dragged = tab.dataset.path;
    event.dataTransfer.effectAllowed = 'move';
  });
  host.addEventListener('dragover', (event) => {
    if (dragged) event.preventDefault();
  });
  host.addEventListener('drop', (event) => {
    const target = event.target.closest('.tab');
    if (!dragged || !target || target.dataset.path === dragged) return;
    event.preventDefault();
    const from = state.tabs.findIndex((tab) => tab.path === dragged);
    const to = state.tabs.findIndex((tab) => tab.path === target.dataset.path);
    const [moved] = state.tabs.splice(from, 1);
    state.tabs.splice(to, 0, moved);
    dragged = null;
    render();
    persist();
  });
}

function tabMenu(event, tab) {
  showMenu([
    { label: 'Сохранить', icon: '💾', hint: 'Ctrl S', onSelect: () => save(tab.path) },
    { label: 'Закрыть', icon: '✕', onSelect: () => close(tab.path) },
    { label: 'Закрыть остальные', onSelect: () => closeOthers(tab.path) },
    { label: 'Закрыть все', onSelect: () => closeAll() },
    { separator: true },
    {
      label: 'Копировать путь',
      icon: '⧉',
      onSelect: async () => {
        const { copyText } = await import('../core/dom.js');
        await copyText(tab.path);
        notify.ok('Путь скопирован.');
      },
    },
  ], { x: event.clientX, y: event.clientY });
}

/* -------------------------------------------- запоминание открытых файлов -- */

function persist() {
  if (!state.project) return;
  prefs.set(`tabs:${state.project.id}`, {
    open: state.tabs.map((tab) => tab.path),
    active: state.activePath,
  });
}

export async function restore() {
  if (!state.project) return;
  const saved = prefs.get(`tabs:${state.project.id}`);
  if (!saved || !saved.open?.length) return;
  for (const path of saved.open.slice(0, 12)) {
    await open(path, { focus: false }).catch(() => {});
  }
  if (saved.active && find(saved.active)) activate(saved.active);
}

on('tabs:changed', render);
