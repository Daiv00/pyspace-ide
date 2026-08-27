/** Проекты: список, создание, переключение, участники, импорт/экспорт ZIP. */
import api from '../core/api.js';
import { clear, downloadUrl, el, humanDate, humanSize, pickFiles, qs } from '../core/dom.js';
import { confirmSheet, openSheet, promptSheet, showMenu } from '../core/modal.js';
import { emit, prefs, state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as editor from './editor.js';
import * as tabs from './tabs.js';
import * as tree from './tree.js';

const TEMPLATES = [
  { id: 'python', icon: '🐍', title: 'Python', hint: 'main.py и requirements.txt' },
  { id: 'web', icon: '🌐', title: 'Веб-сайт', hint: 'index.html, style.css, app.js' },
  { id: 'sql', icon: '🗄', title: 'SQL', hint: 'schema.sql с примером' },
  { id: 'empty', icon: '◻', title: 'Пустой', hint: 'без файлов' },
];

export async function load() {
  const { projects } = await api.projects();
  state.projects = projects;
  emit('projects:loaded', projects);
  return projects;
}

/** Открыть проект: подтянуть детали, дерево и запомнить выбор. */
export async function select(projectId) {
  const { project, members } = await api.project(projectId);
  state.project = project;
  state.members = members;
  state.openFolders = new Set();
  state.tabs = [];
  state.activePath = null;
  editor.disposeAll();
  editor.refreshReadOnly();
  prefs.set('lastProject', project.id);

  const label = qs('#projectName');
  if (label) label.textContent = project.name;
  const status = qs('#statusProject');
  if (status) status.textContent = `проект: ${project.name} · ${humanSize(project.size)}`;

  tabs.render();
  await tree.refresh();
  await tabs.restore();
  emit('project:selected', project);
}

/** Открыть первый доступный проект или предложить создать. */
export async function bootstrap() {
  const projects = await load();
  if (!projects.length) {
    await openCreate({ first: true });
    return;
  }
  const last = prefs.get('lastProject');
  const target = projects.find((project) => project.id === last) || projects[0];
  await select(target.id);
}

export function openSwitcher(anchor) {
  const items = state.projects.map((project) => ({
    label: project.name,
    icon: project.access === 'owner' ? '★' : project.access === 'editor' ? '✎' : '👁',
    hint: humanSize(project.size),
    active: state.project && project.id === state.project.id,
    onSelect: () => select(project.id).catch((error) => notify.error(error.message)),
  }));
  showMenu([
    { heading: 'Проекты' },
    ...items,
    { separator: true },
    { label: 'Новый проект…', icon: '＋', onSelect: () => openCreate() },
    { label: 'Импорт ZIP как новый проект…', icon: '📦', onSelect: () => importAsProject() },
    { separator: true },
    { label: 'Управление проектом…', icon: '⚙', onSelect: () => openManage(), disabled: !state.project },
  ], { anchor, align: 'start' });
}

export function openCreate({ first = false } = {}) {
  let template = 'python';
  const name = el('input', { class: 'input', placeholder: 'Мой проект', autocomplete: 'off' });
  const grid = el('div', { class: 'template-grid' });

  TEMPLATES.forEach((item) => {
    const card = el('button', {
      class: 'template',
      type: 'button',
      'aria-selected': item.id === template ? 'true' : 'false',
      onClick: () => {
        template = item.id;
        grid.querySelectorAll('.template').forEach((node) => node.setAttribute('aria-selected', 'false'));
        card.setAttribute('aria-selected', 'true');
      },
    }, [
      el('span', { class: 'template__icon', text: item.icon }),
      el('b', { text: item.title }),
      el('small', { text: item.hint }),
    ]);
    grid.append(card);
  });

  const submit = async () => {
    const title = name.value.trim();
    if (!title) { name.focus(); return; }
    try {
      const { project } = await api.createProject(title, template);
      await load();
      await select(project.id);
      dialog.close();
      notify.ok(`Проект «${project.name}» создан.`);
    } catch (error) {
      notify.error(error.message);
    }
  };
  name.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });

  const dialog = openSheet({
    title: first ? 'Создайте первый проект' : 'Новый проект',
    subtitle: 'Проект — это отдельная папка с файлами, пакетами и своим терминалом.',
    dismissable: !first,
    body: [
      el('div', { class: 'field' }, [el('label', { text: 'Название' }), name]),
      el('div', { class: 'field' }, [el('label', { text: 'Шаблон' }), grid]),
    ],
    actions: [
      !first ? el('button', { class: 'btn', text: 'Отмена', onClick: () => dialog.close() }) : null,
      el('button', { class: 'btn btn--primary', text: 'Создать', onClick: submit }),
    ].filter(Boolean),
  });
  setTimeout(() => name.focus(), 30);
}

export async function rename() {
  if (!state.project) return;
  const name = await promptSheet({
    title: 'Переименовать проект',
    label: 'Название',
    value: state.project.name,
    confirmText: 'Сохранить',
  });
  if (!name) return;
  try {
    await api.renameProject(state.project.id, name);
    state.project.name = name;
    qs('#projectName').textContent = name;
    await load();
    notify.ok('Название обновлено.');
  } catch (error) {
    notify.error(error.message);
  }
}

export async function remove() {
  if (!state.project) return;
  const yes = await confirmSheet({
    title: 'Удалить проект?',
    message: `«${state.project.name}» и все его файлы будут удалены безвозвратно.`,
    confirmText: 'Удалить проект',
    danger: true,
  });
  if (!yes) return;
  try {
    await api.deleteProject(state.project.id);
    notify.ok('Проект удалён.');
    state.project = null;
    tabs.closeAll();
    await bootstrap();
  } catch (error) {
    notify.error(error.message);
  }
}

export function downloadZip() {
  if (!state.project) return;
  downloadUrl(`/api/projects/${state.project.id}/archive.zip`, `${state.project.name}.zip`);
}

export async function importAsProject() {
  const files = await pickFiles({ multiple: false, accept: '.zip' });
  if (!files.length) return;
  const form = new FormData();
  form.append('file', files[0]);
  const pending = notify.info('Распаковка архива…');
  try {
    const result = await api.importZip(form);
    await load();
    await select(result.project.id);
    notify.ok(result.message);
  } catch (error) {
    notify.error(error.message);
  } finally {
    pending?.remove();
  }
}

export async function importIntoCurrent() {
  if (!state.project) return;
  const files = await pickFiles({ multiple: false, accept: '.zip' });
  if (!files.length) return;
  const form = new FormData();
  form.append('file', files[0]);
  const pending = notify.info('Распаковка архива в проект…');
  try {
    const result = await api.importZipInto(state.project.id, form);
    await tree.refresh();
    notify.ok(result.message);
  } catch (error) {
    notify.error(error.message);
  } finally {
    pending?.remove();
  }
}

/* ------------------------------------------------------- управление проектом */

export function openManage() {
  if (!state.project) return;
  const project = state.project;
  const isOwner = project.access === 'owner';
  const membersBox = el('div', { class: 'card-list' });

  const renderMembers = () => {
    clear(membersBox);
    if (!state.members.length) {
      membersBox.append(el('div', { class: 'empty', text: 'Пока только вы' }));
      return;
    }
    state.members.forEach((member) => {
      membersBox.append(el('div', { class: 'card card--flat' }, [
        el('span', { class: 'card__icon', text: member.role === 'owner' ? '★' : member.role === 'editor' ? '✎' : '👁' }),
        el('div', { class: 'card__main' }, [
          el('div', { class: 'card__title', text: member.username }),
          el('div', { class: 'card__meta', text: member.role === 'owner' ? 'владелец' : member.role === 'editor' ? 'редактор' : 'наблюдатель' }),
        ]),
        isOwner && member.role !== 'owner'
          ? el('button', {
            class: 'btn btn--sm btn--danger',
            text: 'Убрать',
            onClick: async () => {
              try {
                const result = await api.removeMember(project.id, member.user_id ?? member.id);
                state.members = result.members;
                renderMembers();
              } catch (error) { notify.error(error.message); }
            },
          })
          : null,
      ]));
    });
  };
  renderMembers();

  const username = el('input', { class: 'input', placeholder: 'логин пользователя', autocomplete: 'off' });
  const role = el('select', { class: 'select' }, [
    el('option', { value: 'editor', text: 'Редактор — может менять файлы' }),
    el('option', { value: 'viewer', text: 'Наблюдатель — только чтение' }),
  ]);

  const addMember = async () => {
    const login = username.value.trim();
    if (!login) return;
    try {
      const result = await api.addMember(project.id, login, role.value);
      state.members = result.members;
      username.value = '';
      renderMembers();
      notify.ok('Участник добавлен.');
    } catch (error) { notify.error(error.message); }
  };

  const dialog = openSheet({
    title: `Проект «${project.name}»`,
    subtitle: `${humanSize(project.size)} · обновлён ${humanDate(project.updated_at)}`,
    body: [
      el('div', { class: 'stat-grid' }, [
        el('div', { class: 'stat' }, [el('b', { text: String(state.tree.filter((n) => n.type === 'file').length) }), el('small', { text: 'файлов' })]),
        el('div', { class: 'stat' }, [el('b', { text: humanSize(project.size) }), el('small', { text: 'размер' })]),
        el('div', { class: 'stat' }, [el('b', { text: String(state.members.length) }), el('small', { text: 'участников' })]),
      ]),
      el('hr', { class: 'divider' }),
      el('div', { class: 'eyebrow', text: 'Участники' }),
      membersBox,
      isOwner
        ? el('div', { class: 'row', style: { marginTop: '8px' } }, [
          el('div', { class: 'grow' }, [username]),
          role,
          el('button', { class: 'btn btn--primary', text: 'Добавить', onClick: addMember }),
        ])
        : null,
      el('hr', { class: 'divider' }),
      el('div', { class: 'eyebrow', text: 'Действия' }),
      el('div', { class: 'row', style: { flexWrap: 'wrap' } }, [
        el('button', { class: 'btn', text: 'Скачать ZIP', onClick: () => downloadZip() }),
        el('button', { class: 'btn', text: 'Импорт ZIP', onClick: () => { dialog.close(); importIntoCurrent(); } }),
        isOwner ? el('button', { class: 'btn', text: 'Переименовать', onClick: () => { dialog.close(); rename(); } }) : null,
        isOwner ? el('button', { class: 'btn btn--danger', text: 'Удалить проект', onClick: () => { dialog.close(); remove(); } }) : null,
      ].filter(Boolean)),
    ].filter(Boolean),
    actions: [el('button', { class: 'btn', text: 'Закрыть', onClick: () => dialog.close() })],
  });
}
