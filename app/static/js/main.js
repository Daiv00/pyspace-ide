/** Точка сборки интерфейса PySpace IDE. */
import { onBusy } from './core/api.js';
import { el, qs, qsa } from './core/dom.js';
import { closeMenu, closeTopSheet, openSheet } from './core/modal.js';
import { openPalette, registerAll } from './core/palette.js';
import { makeGutter } from './core/split.js';
import { emit, isAdmin, on, prefs, state } from './core/store.js';
import { notify } from './core/toast.js';

import * as admin from './features/admin.js';
import * as auth from './features/auth.js';
import * as dock from './features/dock.js';
import * as drops from './features/drops.js';
import * as editor from './features/editor.js';
import * as packages from './features/packages.js';
import * as preview from './features/preview.js';
import * as projects from './features/projects.js';
import * as runner from './features/runner.js';
import * as search from './features/search.js';
import * as tabs from './features/tabs.js';
import * as terminal from './features/terminal.js';
import * as tree from './features/tree.js';
import * as vault from './features/vault.js';

/* ------------------------------------------------------------------ тема --- */

function setTheme(next) {
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('pyspace.theme', next); } catch { /* приватный режим */ }
  const use = qs('#themeBtn use');
  if (use) use.setAttribute('href', next === 'light' ? '#i-sun' : '#i-moon');
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', next === 'light' ? '#f4f6fb' : '#0b0d12');
  editor.applyTheme();
  terminal.applyTheme();
}

function toggleTheme() {
  setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
}

/* ------------------------------------------------------------- боковые панели */

function showPanel(name) {
  state.panel = name;
  qsa('.rail-btn[data-panel]').forEach((button) => {
    button.setAttribute('aria-selected', button.dataset.panel === name ? 'true' : 'false');
  });
  qsa('.panel[data-panel]').forEach((panel) => {
    if (panel.dataset.panel === name) panel.dataset.active = 'true';
    else delete panel.dataset.active;
  });
  const workbench = qs('#workbench');
  if (workbench && workbench.dataset.sidebar === 'closed') workbench.dataset.sidebar = 'open';
  prefs.set('panel', name);

  if (name === 'packages') packages.refresh();
  if (name === 'drops') drops.refresh();
  if (name === 'vault') vault.refresh();
  if (name === 'admin') admin.refresh();
  if (name === 'search') search.focus();
  setTimeout(() => editor.layout(), 60);
}

function toggleSidebar() {
  const workbench = qs('#workbench');
  if (!workbench) return;
  const open = workbench.dataset.sidebar !== 'closed';
  workbench.dataset.sidebar = open ? 'closed' : 'open';
  prefs.set('sidebarOpen', !open);
  setTimeout(() => editor.layout(), 80);
}

/* -------------------------------------------------------------- горячие клавиши */

function onKeyDown(event) {
  const mod = event.ctrlKey || event.metaKey;
  const key = event.key.toLowerCase();

  if (event.key === 'Escape') {
    if (closeMenu()) return;
    if (closeTopSheet()) return;
  }
  if (!mod) return;

  if (key === 's' && !event.shiftKey) { event.preventDefault(); tabs.save(); return; }
  if (key === 's' && event.shiftKey) { event.preventDefault(); tabs.saveAll(); return; }
  if (key === 'enter') { event.preventDefault(); runner.run(); return; }
  if (key === 'k' && !event.shiftKey) { event.preventDefault(); openPalette(); return; }
  if (key === 'p' && !event.shiftKey) { event.preventDefault(); openFilePalette(); return; }
  if (key === 'p' && event.shiftKey) { event.preventDefault(); openPalette(); return; }
  if (key === '`') { event.preventDefault(); dock.show('terminal'); return; }
  if (key === 'b') { event.preventDefault(); toggleSidebar(); return; }
  if (key === 'j') { event.preventDefault(); dock.toggle(); return; }
  if (key === 'w' && event.shiftKey) { event.preventDefault(); tabs.close(state.activePath); return; }
  if (key === 'e' && event.shiftKey) { event.preventDefault(); showPanel('explorer'); return; }
  if (key === 'f' && event.shiftKey) { event.preventDefault(); showPanel('search'); return; }
  if (key === 'n' && event.altKey) { event.preventDefault(); tree.createFile(); }
}

function openFilePalette() {
  const files = (state.tree || [])
    .filter((node) => node.type === 'file')
    .map((node) => ({
      title: node.path,
      icon: tabs.fileIcon(node.name),
      group: '',
      run: () => tabs.open(node.path),
    }));
  if (!files.length) { notify.info('В проекте пока нет файлов.'); return; }
  openPalette({ items: files, placeholder: 'Найти файл по имени…' });
}

/* ------------------------------------------------------------ палитра команд */

function registerCommands() {
  registerAll([
    { title: 'Запустить активный файл', icon: '▶', group: 'Код', hint: 'Ctrl ⏎', run: () => runner.run() },
    { title: 'Сохранить файл', icon: '💾', group: 'Файл', hint: 'Ctrl S', run: () => tabs.save() },
    { title: 'Сохранить все файлы', icon: '💾', group: 'Файл', hint: 'Ctrl ⇧ S', run: () => tabs.saveAll() },
    { title: 'Найти файл по имени', icon: '🔎', group: 'Файл', hint: 'Ctrl P', run: openFilePalette },
    { title: 'Новый файл', icon: '＋', group: 'Файл', run: () => tree.createFile() },
    { title: 'Новая папка', icon: '📁', group: 'Файл', run: () => tree.createFolder() },
    { title: 'Загрузить файлы в проект', icon: '⇧', group: 'Файл', run: () => tree.uploadInto() },
    { title: 'Закрыть вкладку', icon: '✕', group: 'Файл', hint: 'Ctrl ⇧ W', run: () => tabs.close(state.activePath) },
    { title: 'Закрыть все вкладки', group: 'Файл', run: () => tabs.closeAll() },

    { title: 'Новый проект', icon: '🆕', group: 'Проект', run: () => projects.openCreate() },
    { title: 'Переключить проект', icon: '⇄', group: 'Проект', run: () => projects.openSwitcher(qs('#projectSwitch')) },
    { title: 'Управление проектом', icon: '⚙', group: 'Проект', run: () => projects.openManage() },
    { title: 'Переименовать проект', group: 'Проект', run: () => projects.rename() },
    { title: 'Скачать проект в ZIP', icon: '⤓', group: 'Проект', run: () => projects.downloadZip() },
    { title: 'Импорт ZIP в текущий проект', icon: '📦', group: 'Проект', run: () => projects.importIntoCurrent() },
    { title: 'Импорт ZIP как новый проект', icon: '📦', group: 'Проект', run: () => projects.importAsProject() },
    { title: 'Удалить проект', icon: '🗑', group: 'Проект', run: () => projects.remove() },

    { title: 'Открыть терминал', icon: '▮', group: 'Терминал', hint: 'Ctrl `', run: () => dock.show('terminal') },
    { title: 'Перезапустить терминал', group: 'Терминал', run: () => terminal.restart() },
    { title: 'Прервать процесс (Ctrl+C)', group: 'Терминал', run: () => terminal.interrupt() },
    { title: 'Терминал: git status', group: 'Терминал', run: () => terminal.runCommand('git status') },
    { title: 'Терминал: список файлов', group: 'Терминал', run: () => terminal.runCommand('ls -la') },

    { title: 'Установить пакет pip…', icon: '📦', group: 'Пакеты', run: () => showPanel('packages') },
    { title: 'Обновить список пакетов', group: 'Пакеты', run: () => packages.refresh() },

    { title: 'Открыть живой предпросмотр', icon: '👁', group: 'Вид', run: () => preview.open() },
    { title: 'Закрыть предпросмотр', group: 'Вид', when: () => preview.isOpen(), run: () => preview.close() },
    { title: 'Показать/скрыть боковую панель', group: 'Вид', hint: 'Ctrl B', run: toggleSidebar },
    { title: 'Показать/скрыть нижнюю панель', group: 'Вид', hint: 'Ctrl J', run: () => dock.toggle() },
    { title: 'Сменить тему (светлая/тёмная)', icon: '◐', group: 'Вид', run: toggleTheme },
    { title: 'Перенос длинных строк', group: 'Вид', run: () => {
      const next = editor.getOption('wordWrap', 'off') === 'on' ? 'off' : 'on';
      editor.setOption('wordWrap', next);
      notify.info(`Перенос строк: ${next === 'on' ? 'включён' : 'выключен'}`);
    } },
    { title: 'Миникарта кода', group: 'Вид', run: () => {
      const next = !editor.getOption('minimap', true);
      editor.setOption('minimap', next);
      notify.info(`Миникарта: ${next ? 'включена' : 'выключена'}`);
    } },
    { title: 'Увеличить шрифт редактора', group: 'Вид', run: () => {
      editor.setOption('fontSize', Math.min(24, editor.getOption('fontSize', 14) + 1));
    } },
    { title: 'Уменьшить шрифт редактора', group: 'Вид', run: () => {
      editor.setOption('fontSize', Math.max(10, editor.getOption('fontSize', 14) - 1));
    } },
    { title: 'Форматировать документ', group: 'Код', run: () => editor.action('editor.action.formatDocument') },
    { title: 'Перейти к строке…', group: 'Код', run: () => editor.action('editor.action.gotoLine') },
    { title: 'Поиск по проекту', icon: '🔎', group: 'Код', hint: 'Ctrl ⇧ F', run: () => showPanel('search') },

    { title: 'Создать комнату обмена (QR)', icon: '⇄', group: 'Обмен', run: () => drops.create() },
    { title: 'Полученные файлы', icon: '📥', group: 'Обмен', run: () => showPanel('vault') },

    { title: 'Панель администратора', icon: '🛡', group: 'Админ', when: isAdmin, run: () => admin.openFull() },
    { title: 'Сменить пароль', icon: '🔑', group: 'Аккаунт', run: () => auth.openPasswordChange() },
    { title: 'Выйти из аккаунта', icon: '⎋', group: 'Аккаунт', run: () => auth.logout() },
    { title: 'Справка и горячие клавиши', icon: '?', group: 'Помощь', run: openHelp },
  ]);
}

/* ---------------------------------------------------------------- справка --- */

function openHelp() {
  const rows = [
    ['Ctrl K', 'палитра команд'],
    ['Ctrl P', 'быстрый переход к файлу'],
    ['Ctrl S', 'сохранить · Ctrl ⇧ S — сохранить всё'],
    ['Ctrl Enter', 'запустить активный файл'],
    ['Ctrl `', 'терминал · Ctrl J — свернуть панель'],
    ['Ctrl B', 'боковая панель'],
    ['Ctrl ⇧ F', 'поиск по проекту'],
    ['Ctrl ⇧ W', 'закрыть вкладку'],
    ['F2 / Delete', 'переименовать / удалить в дереве'],
  ];
  const dialog = openSheet({
    title: 'PySpace IDE — справка',
    subtitle: 'Онлайн-среда разработки: проекты, терминал, предпросмотр и обмен файлами.',
    body: [
      el('div', { class: 'eyebrow', text: 'Горячие клавиши' }),
      el('table', { class: 'table' }, [el('tbody', {}, rows.map(([keys, text]) => el('tr', {}, [
        el('td', { style: { width: '140px' } }, [el('kbd', { text: keys })]),
        el('td', { text }),
      ])))]),
      el('hr', { class: 'divider' }),
      el('div', { class: 'eyebrow', text: 'Как это работает' }),
      el('ul', { class: 'dim', style: { margin: 0, paddingLeft: '18px', display: 'grid', gap: '6px' } }, [
        el('li', { text: 'Python-файлы запускаются в папке проекта, поэтому скрипты видят свои данные и могут писать файлы.' }),
        el('li', { text: 'pip ставит пакеты в .packages внутри проекта — они автоматически доступны при запуске и в терминале.' }),
        el('li', { text: 'Терминал — настоящий bash-сеанс в папке проекта: git, python, ls, всё как обычно.' }),
        el('li', { text: 'Предпросмотр открывает файлы проекта по отдельной ссылке в изолированной песочнице и обновляется при сохранении.' }),
        el('li', { text: 'Комната обмена даёт QR-код: телефон загружает файлы без пароля, а вы получаете их в разделе «Полученные файлы».' }),
        el('li', {
          text: state.features.persistent_storage
            ? 'Постоянный диск подключён — файлы сохраняются между перезапусками.'
            : 'Внимание: постоянный диск не подключён. На бесплатном плане Render файлы и база исчезают при каждом редеплое.',
        }),
      ]),
    ],
    actions: [el('button', { class: 'btn btn--primary', text: 'Понятно', onClick: () => dialog.close() })],
  });
}

/* --------------------------------------------------------------- разделители */

function initGutters() {
  makeGutter(qs('#gutterSidebar'), {
    axis: 'x',
    variable: '--w-sidebar',
    min: 190,
    max: () => Math.min(560, window.innerWidth * 0.5),
    key: 'sidebarWidth',
    onMove: () => editor.layout(),
  });
  makeGutter(qs('#gutterDock'), {
    axis: 'y',
    variable: '--h-dock',
    min: 90,
    max: () => Math.max(140, window.innerHeight * 0.72),
    invert: true,
    key: 'dockHeight',
    onMove: () => { editor.layout(); emit('dock:resized'); },
  });
  makeGutter(qs('#gutterPreview'), {
    axis: 'x',
    variable: '--w-preview',
    min: 240,
    max: () => Math.max(320, window.innerWidth * 0.75),
    invert: true,
    key: 'previewWidth',
    onMove: () => editor.layout(),
  });
}

/* ------------------------------------------------------------------ запуск -- */

function wireChrome() {
  qs('#runBtn')?.addEventListener('click', () => runner.run());
  qs('#saveBtn')?.addEventListener('click', () => tabs.save());
  qs('#previewBtn')?.addEventListener('click', () => preview.toggle(state.activePath || ''));
  qs('#terminalBtn')?.addEventListener('click', () => dock.show('terminal'));
  qs('#paletteBtn')?.addEventListener('click', () => openPalette());
  qs('#themeBtn')?.addEventListener('click', toggleTheme);
  qs('#helpBtn')?.addEventListener('click', openHelp);
  qs('#sidebarToggle')?.addEventListener('click', toggleSidebar);
  qs('#projectSwitch')?.addEventListener('click', (event) => projects.openSwitcher(event.currentTarget));
  qs('#statusProject')?.addEventListener('click', () => projects.openManage());
  qs('#statusLang')?.addEventListener('click', () => editor.action('editor.action.gotoLine'));

  qs('#newFileBtn')?.addEventListener('click', () => tree.createFile());
  qs('#newFolderBtn')?.addEventListener('click', () => tree.createFolder());
  qs('#uploadBtn')?.addEventListener('click', () => tree.uploadInto());
  qs('#treeRefreshBtn')?.addEventListener('click', () => tree.refresh());
  qs('#downloadZipBtn')?.addEventListener('click', () => projects.downloadZip());
  qs('#importZipBtn')?.addEventListener('click', () => projects.importIntoCurrent());
  qs('#closeOthersBtn')?.addEventListener('click', () => tabs.closeOthers(state.activePath));
  qs('#dockClearBtn')?.addEventListener('click', () => {
    if (state.dock === 'output') runner.reset('');
    else terminal.restart();
  });

  qsa('.rail-btn[data-panel]').forEach((button) => {
    button.addEventListener('click', () => showPanel(button.dataset.panel));
  });

  document.addEventListener('keydown', onKeyDown);
  window.addEventListener('beforeunload', (event) => {
    if (tabs.dirtyCount() > 0) { event.preventDefault(); event.returnValue = ''; }
  });

  onBusy((pending) => {
    const dot = qs('#connDot');
    const text = qs('#connText');
    if (!dot || !text || runner.isRunning()) return;
    dot.dataset.state = pending ? 'busy' : 'ok';
    text.textContent = pending ? 'обмен данными…' : 'готов';
  });
}

async function startWorkbench() {
  auth.showApp();
  wireChrome();
  registerCommands();
  initGutters();
  dock.init();
  search.init();
  packages.init();
  drops.init();
  vault.init();
  admin.init();
  preview.init();
  terminal.init();
  tree.enableDropzone();

  if (prefs.get('sidebarOpen', true) === false) qs('#workbench').dataset.sidebar = 'closed';
  showPanel(prefs.get('panel', 'explorer'));

  try {
    await editor.init();
  } catch (error) {
    notify.error(error.message || 'Редактор не загрузился.');
  }

  try {
    await projects.bootstrap();
  } catch (error) {
    notify.error(error.message || 'Не удалось загрузить проекты.');
  }

  vault.refresh();
  if (isAdmin()) admin.refresh();
  if (prefs.get('previewOpen', false) && state.features.preview) preview.open();

  window.addEventListener('resize', () => editor.layout());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) editor.layout(); });
}

function boot() {
  const node = qs('#bootData');
  let data = {};
  try {
    data = JSON.parse(node?.textContent || '{}');
  } catch { /* останется пустым */ }

  if (data.features) state.features = { ...state.features, ...data.features };
  if (data.limits) state.limits = { ...state.limits, ...data.limits };
  state.user = data.user || null;

  setTheme(document.documentElement.dataset.theme || 'dark');
  auth.init();

  on('auth:signed-in', () => { startWorkbench(); });

  if (state.user) startWorkbench();
  else auth.showGate();
}

boot();
