/** Всплывающие уведомления. */
import { el, qs } from './dom.js';

const ICONS = { info: 'ℹ', success: '✓', error: '✕', warn: '!' };
const LIMIT = 4;

export function toast(message, kind = 'info', timeout = 4200) {
  const host = qs('#toasts');
  if (!host) return null;

  while (host.children.length >= LIMIT) host.firstElementChild.remove();

  const node = el('div', { class: `toast toast--${kind}`, role: 'status' }, [
    el('span', { class: 'toast__icon', text: ICONS[kind] || ICONS.info }),
    el('div', { class: 'toast__body', text: String(message) }),
    el('button', { class: 'toast__close', title: 'Закрыть', text: '✕', onClick: () => dismiss(node) }),
  ]);
  host.append(node);

  if (timeout > 0) setTimeout(() => dismiss(node), timeout);
  return node;
}

function dismiss(node) {
  if (!node || !node.isConnected) return;
  node.dataset.leaving = 'true';
  setTimeout(() => node.remove(), 260);
}

export const notify = {
  info: (message) => toast(message, 'info'),
  ok: (message) => toast(message, 'success'),
  warn: (message) => toast(message, 'warn'),
  error: (message) => toast(message && message.message ? message.message : message, 'error', 7000),
};
