/** Полученные файлы: список, скачивание, выдача доступа (для админа). */
import api from '../core/api.js';
import { clear, downloadUrl, el, humanDate, qs } from '../core/dom.js';
import { confirmSheet, showMenu } from '../core/modal.js';
import { isAdmin } from '../core/store.js';
import { notify } from '../core/toast.js';

let users = [];

export async function refresh() {
  const host = qs('#vaultList');
  if (!host) return;
  try {
    const { files } = await api.vault();
    render(files);
    const badge = qs('#vaultBadge');
    if (badge) {
      badge.textContent = String(files.length);
      badge.classList.toggle('is-hidden', files.length === 0);
    }
  } catch (error) {
    clear(host).append(el('div', { class: 'empty', text: error.message }));
  }
}

function render(files) {
  const host = qs('#vaultList');
  clear(host);
  if (!files.length) {
    host.append(el('div', { class: 'empty' }, [
      el('strong', { text: 'Файлов нет' }),
      'Всё, что загрузят в комнату обмена, появится здесь.',
    ]));
    return;
  }
  files.forEach((file) => {
    host.append(el('div', {
      class: 'card',
      onContextMenu: (event) => { event.preventDefault(); menu(event, file); },
    }, [
      el('span', { class: 'card__icon', text: file.kind === 'image' ? '🖼' : '📄' }),
      el('button', {
        class: 'card__main',
        style: { textAlign: 'left', background: 'none', border: 0 },
        onClick: () => download(file),
      }, [
        el('div', { class: 'card__title', text: file.original_name }),
        el('div', {
          class: 'card__meta',
          text: `${file.size_human} · ${humanDate(file.created_at)}${file.recipient_name ? ` · выдан ${file.recipient_name}` : ''}`,
        }),
      ]),
      el('button', {
        class: 'btn btn--ghost btn--icon btn--sm',
        title: 'Действия',
        text: '⋯',
        onClick: (event) => menu(event, file),
      }),
    ]));
  });
}

function download(file) {
  downloadUrl(`/api/drops/vault/files/${file.id}/download`, file.original_name);
}

function menu(event, file) {
  const items = [
    { heading: file.original_name },
    { label: 'Скачать', icon: '⤓', onSelect: () => download(file) },
  ];
  if (isAdmin()) {
    items.push({ separator: true }, {
      label: 'Выдать пользователю…',
      icon: '👤',
      onSelect: () => assign(file),
    }, {
      label: 'Снять доступ',
      onSelect: async () => {
        try {
          const result = await api.adminAssignFile(file.id, null);
          notify.ok(result.message);
          await refresh();
        } catch (error) { notify.error(error.message); }
      },
    }, {
      label: 'Удалить файл',
      icon: '🗑',
      danger: true,
      onSelect: async () => {
        const yes = await confirmSheet({
          title: 'Удалить файл?',
          message: `«${file.original_name}» будет удалён с диска.`,
          confirmText: 'Удалить',
          danger: true,
        });
        if (!yes) return;
        try {
          await api.adminDeleteFile(file.id);
          notify.ok('Файл удалён.');
          await refresh();
        } catch (error) { notify.error(error.message); }
      },
    });
  }
  showMenu(items, { x: event.clientX, y: event.clientY });
}

async function assign(file) {
  if (!users.length) {
    try {
      const overview = await api.adminOverview();
      users = overview.users;
    } catch (error) { notify.error(error.message); return; }
  }
  showMenu([
    { heading: 'Кому выдать файл' },
    ...users.map((user) => ({
      label: `${user.username}${user.role === 'admin' ? ' · админ' : ''}`,
      onSelect: async () => {
        try {
          const result = await api.adminAssignFile(file.id, user.id);
          notify.ok(result.message);
          await refresh();
        } catch (error) { notify.error(error.message); }
      },
    })),
  ], { x: window.innerWidth / 2 - 100, y: 120 });
}

export function init() {
  qs('#vaultRefreshBtn')?.addEventListener('click', refresh);
}
