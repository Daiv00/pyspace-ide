/** Комнаты обмена по QR-коду. */
import api from '../core/api.js';
import { clear, copyText, el, humanDate, qs } from '../core/dom.js';
import { confirmSheet, openSheet, promptSheet } from '../core/modal.js';
import { notify } from '../core/toast.js';

let cache = [];

export async function refresh() {
  const host = qs('#dropsList');
  if (!host) return;
  try {
    const { drops } = await api.drops();
    cache = drops;
    render();
  } catch (error) {
    clear(host).append(el('div', { class: 'empty', text: error.message }));
  }
}

function render() {
  const host = qs('#dropsList');
  if (!host) return;
  clear(host);
  if (!cache.length) {
    host.append(el('div', { class: 'empty' }, [
      el('strong', { text: 'Комнат пока нет' }),
      'Создайте комнату и отсканируйте QR телефоном.',
    ]));
    return;
  }
  cache.forEach((drop) => {
    host.append(el('button', {
      class: 'card',
      onClick: () => openQr(drop),
    }, [
      el('span', { class: 'card__icon', text: drop.active ? '⇄' : '✕' }),
      el('div', { class: 'card__main' }, [
        el('div', { class: 'card__title', text: drop.label || `Комната ${drop.token}` }),
        el('div', { class: 'card__meta', text: `${drop.items} файл(ов) · ${humanDate(drop.created_at)}` }),
      ]),
      el('span', { class: `chip ${drop.active ? 'chip--success' : ''}`, text: drop.active ? 'открыта' : 'закрыта' }),
    ]));
  });
}

export async function create() {
  const label = await promptSheet({
    title: 'Новая комната обмена',
    label: 'Название (необязательно)',
    placeholder: 'Фото с телефона',
    confirmText: 'Создать',
    hint: 'Ссылка и QR-код работают без пароля, пока комната открыта.',
  });
  if (label === null) return;
  try {
    const { drop } = await api.createDrop(label || '');
    await refresh();
    openQr(drop);
  } catch (error) {
    notify.error(error.message);
  }
}

export function openQr(drop) {
  const url = drop.url || `${location.origin}/d/${drop.token}`;
  const dialog = openSheet({
    title: drop.label || 'Комната обмена',
    subtitle: 'Отсканируйте код телефоном или отправьте ссылку.',
    size: 'narrow',
    body: [
      el('div', { class: 'qr-block' }, [
        el('div', { class: 'qr-frame' }, [
          el('img', { src: `/api/drops/${drop.token}/qr.png`, alt: 'QR-код комнаты обмена' }),
        ]),
        el('div', { class: 'link-box' }, [
          el('span', { class: 'grow', text: url }),
          el('button', {
            class: 'btn btn--sm',
            text: 'Копировать',
            onClick: async () => {
              await copyText(url);
              notify.ok('Ссылка скопирована.');
            },
          }),
        ]),
        el('p', { class: 'muted', style: { fontSize: 'var(--fs-sm)' }, text: `Код комнаты: ${drop.token}` }),
      ]),
    ],
    actions: [
      el('button', {
        class: 'btn btn--danger',
        text: 'Удалить комнату',
        onClick: async () => {
          const yes = await confirmSheet({
            title: 'Удалить комнату?',
            message: 'Ссылка перестанет работать, полученные файлы будут удалены.',
            confirmText: 'Удалить',
            danger: true,
          });
          if (!yes) return;
          try {
            await api.deleteDrop(drop.token);
            dialog.close();
            await refresh();
            notify.ok('Комната удалена.');
          } catch (error) { notify.error(error.message); }
        },
      }),
      el('button', {
        class: 'btn',
        text: 'Закрыть доступ',
        onClick: async () => {
          try {
            await api.revokeDrop(drop.token);
            dialog.close();
            await refresh();
            notify.ok('Доступ закрыт.');
          } catch (error) { notify.error(error.message); }
        },
      }),
      el('button', { class: 'btn btn--primary', text: 'Готово', onClick: () => dialog.close() }),
    ],
  });
}

export function init() {
  qs('#dropNewBtn')?.addEventListener('click', create);
}
