/** Поиск по файлам проекта. */
import api from '../core/api.js';
import { clear, debounce, el, qs } from '../core/dom.js';
import { state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as tabs from './tabs.js';

function highlight(text, query) {
  const index = text.toLowerCase().indexOf(query.toLowerCase());
  if (index < 0) return [el('span', { text })];
  return [
    el('span', { text: text.slice(0, index) }),
    el('mark', {
      text: text.slice(index, index + query.length),
      style: { background: 'var(--accent-soft)', color: 'var(--accent-hot)', borderRadius: '3px' },
    }),
    el('span', { text: text.slice(index + query.length) }),
  ];
}

async function run() {
  const host = qs('#searchResults');
  const query = qs('#searchQuery')?.value.trim() || '';
  if (!host) return;
  clear(host);
  if (query.length < 2 || !state.project) return;

  host.append(el('div', { class: 'row', style: { padding: '8px 4px' } }, [
    el('span', { class: 'spinner' }), el('span', { class: 'muted', text: 'Ищем…' }),
  ]));

  try {
    const { hits } = await api.searchFiles(state.project.id, query, qs('#searchCase')?.checked);
    clear(host);
    if (!hits.length) {
      host.append(el('div', { class: 'empty', text: 'Совпадений не найдено' }));
      return;
    }
    const byFile = new Map();
    hits.forEach((hit) => {
      if (!byFile.has(hit.path)) byFile.set(hit.path, []);
      byFile.get(hit.path).push(hit);
    });

    host.append(el('p', {
      class: 'muted',
      style: { fontSize: 'var(--fs-sm)', margin: '0 4px 8px' },
      text: `${hits.length} совпадений в ${byFile.size} файлах`,
    }));

    byFile.forEach((group, path) => {
      const rows = group.map((hit) => el('button', {
        class: 'menu__item',
        onClick: () => tabs.open(path, { line: hit.line }),
      }, [
        el('span', { class: 'menu__hint', text: String(hit.line) }),
        el('span', { class: 'grow truncate mono', style: { fontSize: 'var(--fs-sm)' } }, highlight(hit.preview, query)),
      ]));
      host.append(el('div', { style: { marginBottom: '10px' } }, [
        el('div', {
          class: 'eyebrow',
          style: { padding: '0 4px 4px', letterSpacing: '0.06em', textTransform: 'none', color: 'var(--muted)' },
          text: path,
        }),
        ...rows,
      ]));
    });
  } catch (error) {
    clear(host);
    notify.error(error.message);
  }
}

export function init() {
  const input = qs('#searchQuery');
  const debounced = debounce(run, 320);
  input?.addEventListener('input', debounced);
  qs('#searchCase')?.addEventListener('change', run);
  qs('#searchForm')?.addEventListener('submit', (event) => { event.preventDefault(); run(); });
}

export function focus() {
  qs('#searchQuery')?.focus();
}
