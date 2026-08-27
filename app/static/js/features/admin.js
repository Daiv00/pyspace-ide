/** Панель администратора: пользователи, роли, состояние сервера. */
import api from '../core/api.js';
import { clear, el, qs } from '../core/dom.js';
import { confirmSheet, openSheet, promptSheet } from '../core/modal.js';
import { state } from '../core/store.js';
import { notify } from '../core/toast.js';

let overview = null;
let maintenance = null;

export async function refresh() {
  const host = qs('#adminPanelBody');
  if (!host) return;
  try {
    overview = await api.adminOverview();
    try {
      maintenance = await api.maintenanceStatus();
    } catch {
      maintenance = null;
    }
    renderSidebar();
  } catch (error) {
    clear(host).append(el('div', { class: 'empty', text: error.message }));
  }
}

/** Время «сколько назад» из ISO-метки UTC. */
function ago(iso) {
  if (!iso) return 'ещё не было';
  const delta = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (delta < 90) return 'только что';
  if (delta < 3600) return `${Math.round(delta / 60)} мин назад`;
  if (delta < 86400) return `${Math.round(delta / 3600)} ч назад`;
  return `${Math.round(delta / 86400)} дн назад`;
}

function renderMaintenance(host) {
  if (!maintenance) return;
  const ping = maintenance.keepalive || {};
  const copy = maintenance.backup || {};

  const line = (label, value, good) => el('div', { class: 'row-between', style: { padding: '5px 2px' } }, [
    el('span', { class: 'muted', style: { fontSize: 'var(--fs-sm)' }, text: label }),
    el('span', { class: `chip ${good ? 'chip--success' : 'chip--warn'}`, text: value }),
  ]);

  host.append(
    el('div', { class: 'eyebrow', style: { margin: '12px 2px 4px' }, text: 'Обслуживание' }),
    line('Самопинг', ping.enabled ? `каждые ${Math.round((ping.interval || 0) / 60)} мин` : 'выключен', !!ping.enabled),
    ping.enabled ? line('Последний пинг', ping.last_error ? 'ошибка' : ago(ping.last_at), !ping.last_error) : null,
    line('Копии данных', copy.configured ? ago(copy.last_backup_at) : 'не настроены', !!copy.configured),
  );

  if (copy.configured) {
    host.append(el('p', {
      class: 'muted mono',
      style: { fontSize: '10px', margin: '4px 2px', wordBreak: 'break-all' },
      text: `${copy.repo} · ${copy.path}${maintenance.last_backup_size_human ? ` · ${maintenance.last_backup_size_human}` : ''}`,
    }));
    if (copy.last_error) {
      host.append(el('p', { class: 'muted', style: { fontSize: '10px', color: 'var(--danger)' }, text: copy.last_error }));
    }
    host.append(el('div', { class: 'table__actions', style: { marginTop: '6px' } }, [
      el('button', {
        class: 'btn btn--sm btn--primary',
        text: 'Сохранить копию',
        onClick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          try {
            const result = await api.maintenanceBackup();
            notify.ok(`Копия сохранена${result.size_human ? ` · ${result.size_human}` : ''}`);
            await refresh();
          } catch (error) {
            notify.error(error.message);
          } finally {
            button.disabled = false;
          }
        },
      }),
      el('button', {
        class: 'btn btn--sm',
        text: 'Восстановить',
        onClick: async () => {
          const yes = await confirmSheet({
            title: 'Восстановить данные из копии?',
            message: 'Файлы проектов и база будут заменены содержимым последней копии. Несохранённые изменения потеряются, страницу нужно будет обновить.',
            confirmText: 'Восстановить',
            danger: true,
          });
          if (!yes) return;
          try {
            const result = await api.maintenanceRestore();
            notify.ok(`Восстановлено файлов: ${result.result.restored}. Обновите страницу.`);
          } catch (error) {
            notify.error(error.message);
          }
        },
      }),
    ]));
  } else {
    host.append(el('p', {
      class: 'muted',
      style: { fontSize: '10px', margin: '4px 2px' },
      text: 'Задайте PYSPACE_BACKUP_REPO и PYSPACE_BACKUP_TOKEN — данные будут сами уезжать в приватный репозиторий GitHub.',
    }));
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

  renderMaintenance(host);
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
