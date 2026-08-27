/** Панель администратора: пользователи, роли, состояние сервера. */
import api from '../core/api.js';
import { clear, el, qs } from '../core/dom.js';
import { confirmSheet, openSheet, promptSheet } from '../core/modal.js';
import { state } from '../core/store.js';
import { notify } from '../core/toast.js';

let overview = null;

export async function refresh() {
  const host = qs('#adminPanelBody');
  if (!host) return;
  try {
    overview = await api.adminOverview();
    renderSidebar();
  } catch (error) {
    clear(host).append(el('div', { class: 'empty', text: error.message }));
  }
}

function renderSidebar() {
  const host = qs('#adminPanelBody');
  if (!host || !overview) return;
  clear(host);
  const { stats, environment } = overview;

  host.append(el('div', { class: 'stat-grid', style: { marginBottom: '12px' } }, [
    el('div', { class: 'stat' }, [el('b', { text: String(stats.users) }), el('small', { text: 'пользователей' })]),
    el('div', { class: 'stat' }, [el('b', { text: String(stats.projects) }), el('small', { text: 'проектов' })]),
    el('div', { class: 'stat' }, [el('b', { text: String(stats.active_drops) }), el('small', { text: 'комнат' })]),
    el('div', { class: 'stat' }, [el('b', { text: String(stats.received_files) }), el('small', { text: 'файлов' })]),
  ]));

  const flag = (label, good, note) => el('div', { class: 'row-between', style: { padding: '5px 2px' } }, [
    el('span', { class: 'muted', style: { fontSize: 'var(--fs-sm)' }, text: label }),
    el('span', { class: `chip ${good ? 'chip--success' : 'chip--warn'}`, text: note }),
  ]);

  host.append(
    el('div', { class: 'eyebrow', style: { margin: '4px 2px' }, text: 'Сервер' }),
    flag('Постоянный диск', environment.persistent_storage, environment.persistent_storage ? 'подключён' : 'нет (данные исчезнут)'),
    flag('Секретный ключ', environment.secret_from_env, environment.secret_from_env ? 'из окружения' : 'сгенерирован'),
    flag('Терминал', environment.terminal, environment.terminal ? 'включён' : 'выключен'),
    flag('Регистрация', environment.registration, environment.registration ? 'открыта' : 'закрыта'),
    el('p', {
      class: 'muted mono',
      style: { fontSize: '10px', marginTop: '8px', wordBreak: 'break-all' },
      text: environment.data_dir,
    }),
  );
}

export async function openFull() {
  if (!overview) await refresh();
  if (!overview) return;

  const table = el('tbody');
  const dialog = openSheet({
    title: 'Администрирование',
    subtitle: `${overview.stats.users} пользователей · ${overview.stats.admins} админ(ов) · получено ${overview.stats.received_bytes_human}`,
    size: 'wide',
    body: [
      el('div', { class: 'row-between' }, [
        el('div', { class: 'eyebrow', text: 'Пользователи' }),
        el('button', { class: 'btn btn--sm btn--primary', text: '＋ Добавить', onClick: () => createUser(redraw) }),
      ]),
      el('table', { class: 'table' }, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'Логин' }),
          el('th', { text: 'Роль' }),
          el('th', { text: 'Создан' }),
          el('th', { text: '' }),
        ])]),
        table,
      ]),
    ],
    actions: [el('button', { class: 'btn', text: 'Закрыть', onClick: () => dialog.close() })],
  });

  function redraw() {
    clear(table);
    overview.users.forEach((user) => {
      const self = state.user && user.id === state.user.id;
      table.append(el('tr', {}, [
        el('td', {}, [el('span', { text: user.username }), self ? el('span', { class: 'chip', text: 'это вы', style: { marginLeft: '6px' } }) : null]),
        el('td', {}, [el('span', { class: `chip ${user.role === 'admin' ? 'chip--accent' : ''}`, text: user.role === 'admin' ? 'админ' : 'пользователь' })]),
        el('td', { class: 'muted', text: String(user.created_at || '').slice(0, 10) }),
        el('td', {}, [el('div', { class: 'table__actions' }, [
          el('button', {
            class: 'btn btn--sm',
            text: user.role === 'admin' ? 'Снять админа' : 'Сделать админом',
            onClick: () => patchUser(user.id, { role: user.role === 'admin' ? 'user' : 'admin' }, redraw),
          }),
          el('button', {
            class: 'btn btn--sm',
            text: 'Пароль',
            onClick: async () => {
              const password = await promptSheet({
                title: `Новый пароль для ${user.username}`,
                label: 'Пароль',
                placeholder: 'минимум 8 символов',
                confirmText: 'Сменить',
              });
              if (password) patchUser(user.id, { password }, redraw);
            },
          }),
          !self
            ? el('button', {
              class: 'btn btn--sm btn--danger',
              text: 'Удалить',
              onClick: async () => {
                const yes = await confirmSheet({
                  title: `Удалить ${user.username}?`,
                  message: 'Все проекты и файлы этого пользователя будут удалены.',
                  confirmText: 'Удалить',
                  danger: true,
                });
                if (!yes) return;
                try {
                  const result = await api.adminDeleteUser(user.id);
                  overview.users = result.users;
                  redraw();
                  notify.ok('Пользователь удалён.');
                } catch (error) { notify.error(error.message); }
              },
            })
            : null,
        ])]),
      ]));
    });
  }
  redraw();
}

async function patchUser(id, patch, redraw) {
  try {
    const result = await api.adminUpdateUser(id, patch);
    overview.users = result.users;
    redraw();
    renderSidebar();
    notify.ok('Изменения сохранены.');
    if (result.self_changed && patch.role === 'user') {
      notify.warn('Вы сняли с себя права администратора — обновите страницу.');
    }
  } catch (error) { notify.error(error.message); }
}

async function createUser(redraw) {
  const username = await promptSheet({ title: 'Новый пользователь', label: 'Логин', placeholder: 'ivan' });
  if (!username) return;
  const password = await promptSheet({
    title: `Пароль для ${username}`,
    label: 'Пароль',
    placeholder: 'минимум 8 символов',
    confirmText: 'Создать',
  });
  if (!password) return;
  try {
    const result = await api.adminCreateUser(username, password, 'user');
    overview.users = result.users;
    redraw?.();
    await refresh();
    notify.ok(`Пользователь ${username} создан.`);
  } catch (error) { notify.error(error.message); }
}

export function init() {
  qs('#adminRefreshBtn')?.addEventListener('click', refresh);
  qs('#adminOpenBtn')?.addEventListener('click', openFull);
}
