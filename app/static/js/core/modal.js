/** Модальные окна, подтверждения, запрос строки и контекстные меню. */
import { clear, el, qs } from './dom.js';

const layers = () => qs('#layers');
const stack = [];

function trapFocus(sheet) {
  const focusable = sheet.querySelectorAll(
    'input:not([disabled]), textarea, select, button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  sheet.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

/**
 * Открыть модальное окно.
 * @returns {{close: Function, body: HTMLElement, foot: HTMLElement, sheet: HTMLElement}}
 */
export function openSheet({
  title,
  subtitle = '',
  body = [],
  actions = [],
  size = '',
  onClose = null,
  dismissable = true,
} = {}) {
  const bodyNode = el('div', { class: 'sheet__body' }, body);
  const footNode = el('div', { class: 'sheet__foot' }, actions);
  const sheet = el('div', { class: `sheet ${size ? `sheet--${size}` : ''}`, role: 'dialog', 'aria-modal': 'true' }, [
    el('div', { class: 'sheet__head' }, [
      el('div', { class: 'grow' }, [
        el('div', { class: 'sheet__title', text: title }),
        subtitle ? el('div', { class: 'sheet__sub', text: subtitle }) : null,
      ]),
      dismissable
        ? el('button', { class: 'sheet__close', title: 'Закрыть (Esc)', text: '✕', onClick: () => close() })
        : null,
    ]),
    bodyNode,
    actions.length ? footNode : null,
  ]);

  const overlay = el('div', { class: 'overlay' }, [sheet]);
  if (dismissable) {
    overlay.addEventListener('mousedown', (event) => {
      if (event.target === overlay) close();
    });
  }

  const entry = { overlay, close };
  stack.push(entry);
  layers().append(overlay);
  trapFocus(sheet);

  const firstField = sheet.querySelector('input, textarea, select');
  (firstField || sheet.querySelector('.btn--primary') || sheet).focus?.();

  let closed = false;
  function close(result) {
    if (closed) return;
    closed = true;
    overlay.remove();
    const index = stack.indexOf(entry);
    if (index >= 0) stack.splice(index, 1);
    if (onClose) onClose(result);
  }

  return { close, body: bodyNode, foot: footNode, sheet, overlay };
}

export function closeTopSheet() {
  const top = stack[stack.length - 1];
  if (top) {
    top.close();
    return true;
  }
  return false;
}

export const hasOpenSheet = () => stack.length > 0;

/** Подтверждение. Возвращает Promise<boolean>. */
export function confirmSheet({ title, message, confirmText = 'Подтвердить', danger = false }) {
  return new Promise((resolve) => {
    let answered = false;
    const settle = (value) => {
      if (answered) return;
      answered = true;
      resolve(value);
    };
    const dialog = openSheet({
      title,
      size: 'narrow',
      body: [el('p', { class: 'dim', text: message })],
      onClose: () => settle(false),
      actions: [
        el('button', { class: 'btn', text: 'Отмена', onClick: () => dialog.close() }),
        el('button', {
          class: `btn ${danger ? 'btn--danger' : 'btn--primary'}`,
          text: confirmText,
          onClick: () => { settle(true); dialog.close(); },
        }),
      ],
    });
  });
}

/** Запрос строки. Возвращает Promise<string|null>. */
export function promptSheet({ title, label, value = '', placeholder = '', confirmText = 'Готово', hint = '' }) {
  return new Promise((resolve) => {
    let answered = false;
    const settle = (result) => {
      if (answered) return;
      answered = true;
      resolve(result);
    };
    const input = el('input', { class: 'input', value, placeholder, autocomplete: 'off' });
    const submit = () => {
      const text = input.value.trim();
      if (!text) { input.focus(); return; }
      settle(text);
      dialog.close();
    };
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); submit(); }
    });
    const dialog = openSheet({
      title,
      size: 'narrow',
      body: [
        el('div', { class: 'field' }, [el('label', { text: label }), input]),
        hint ? el('p', { class: 'muted', style: { fontSize: 'var(--fs-sm)' }, text: hint }) : null,
      ],
      onClose: () => settle(null),
      actions: [
        el('button', { class: 'btn', text: 'Отмена', onClick: () => dialog.close() }),
        el('button', { class: 'btn btn--primary', text: confirmText, onClick: submit }),
      ],
    });
    setTimeout(() => { input.focus(); input.select(); }, 30);
  });
}

/* ------------------------------------------------------------ меню ------- */

let openMenu = null;

export function closeMenu() {
  if (openMenu) {
    openMenu.remove();
    openMenu = null;
    return true;
  }
  return false;
}

/**
 * Показать меню у координат или у элемента.
 * items: [{label, hint, icon, danger, active, disabled, onSelect} | {separator:true} | {heading:'…'}]
 */
export function showMenu(items, { x, y, anchor, align = 'start' } = {}) {
  closeMenu();
  const menu = el('div', { class: 'menu', role: 'menu' });

  for (const item of items) {
    if (!item) continue;
    if (item.separator) { menu.append(el('div', { class: 'menu__sep' })); continue; }
    if (item.heading) { menu.append(el('div', { class: 'menu__label', text: item.heading })); continue; }
    const button = el('button', {
      class: `menu__item ${item.danger ? 'menu__item--danger' : ''}`,
      role: 'menuitem',
      dataset: item.active ? { active: 'true' } : {},
      disabled: item.disabled || false,
      onClick: () => { closeMenu(); item.onSelect?.(); },
    }, [
      item.icon ? el('span', { text: item.icon, style: { width: '16px', textAlign: 'center' } }) : null,
      el('span', { class: 'grow', text: item.label }),
      item.hint ? el('span', { class: 'menu__hint', text: item.hint }) : null,
    ]);
    menu.append(button);
  }

  layers().append(menu);

  const rect = anchor ? anchor.getBoundingClientRect() : null;
  let left = x !== undefined ? x : rect ? (align === 'end' ? rect.right - menu.offsetWidth : rect.left) : 0;
  let top = y !== undefined ? y : rect ? rect.bottom + 6 : 0;
  left = Math.max(8, Math.min(left, window.innerWidth - menu.offsetWidth - 8));
  top = Math.max(8, Math.min(top, window.innerHeight - menu.offsetHeight - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;

  openMenu = menu;
  setTimeout(() => {
    const off = (event) => {
      if (!menu.contains(event.target)) { closeMenu(); document.removeEventListener('mousedown', off); }
    };
    document.addEventListener('mousedown', off);
  }, 0);
  return menu;
}

export { clear };
