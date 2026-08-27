/** Запуск веб-приложения проекта (Flask, FastAPI, http.server…) и его показ. */
import api from '../core/api.js';
import { qs } from '../core/dom.js';
import { on, state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as dock from './dock.js';
import * as runner from './runner.js';
import * as tabs from './tabs.js';

let busy = false;
let pollTimer = null;

const liveUrl = () => (state.project ? `/live/${state.project.preview_token}/` : '');

function paint(info) {
  const running = Boolean(info && info.running);
  state.webapp = info || { running: false };
  const button = qs('#serverBtn');
  if (button) {
    button.dataset.running = running ? 'true' : 'false';
    button.title = running
      ? `Остановить сервер (${info.path} · порт ${info.port})`
      : 'Запустить активный файл как веб-сервер';
  }
  const label = qs('#serverState');
  if (label) {
    label.textContent = running ? `сервер: ${info.path} · порт ${info.port}` : '';
    label.hidden = !running;
  }
}

/** Показать приложение в панели предпросмотра. */
async function showInPreview() {
  const preview = await import('./preview.js');
  preview.openUrl(liveUrl(), 'сервер проекта');
}

export async function refresh() {
  if (!state.project) return;
  try {
    const { webapp } = await api.webappStatus(state.project.id);
    paint(webapp);
  } catch { /* нет доступа или проект сменился */ }
}

export async function start(path = state.activePath, { note = '' } = {}) {
  if (busy) return;
  if (!state.project) { notify.warn('Выберите проект.'); return; }
  if (!path || !/\.py$/i.test(path)) {
    notify.warn('Откройте .py-файл сервера — например app.py.');
    return;
  }

  busy = true;
  dock.show('output');
  dock.expand();
  runner.reset('');
  if (note) runner.log(note, 'note');
  runner.log(`▶ сервер: ${path}`, 'note');
  try {
    await tabs.save(path, { silent: true });
    const { webapp } = await api.webappStart(state.project.id, path);
    paint(webapp);
    if (webapp.log) runner.log(webapp.log);
    if (webapp.error) {
      runner.log(`✕ ${webapp.error}`, 'bad');
      notify.error('Сервер не запустился — смотрите вывод.');
      return;
    }
    if (webapp.warning) {
      runner.log(`⚠ ${webapp.warning}`, 'warn');
      notify.warn('Процесс запущен, но порт не открыт.');
    } else {
      runner.log(`✓ сервер слушает порт ${webapp.port} · ${liveUrl()}`, 'good');
      notify.ok('Сервер запущен.');
    }
    await showInPreview();
    startPolling();
  } catch (error) {
    runner.log(`✕ ${error.message}`, 'bad');
    notify.error(error.message);
  } finally {
    busy = false;
  }
}

export async function stop() {
  if (!state.project) return;
  busy = true;
  try {
    const { webapp } = await api.webappStop(state.project.id);
    paint(webapp);
    stopPolling();
    notify.ok('Сервер остановлен.');
  } catch (error) {
    notify.error(error.message);
  } finally {
    busy = false;
  }
}

export async function toggle() {
  if (state.webapp && state.webapp.running) await stop();
  else await start();
}

function startPolling() {
  stopPolling();
  // Раз в 5 секунд проверяем, не упал ли процесс сам.
  pollTimer = setInterval(async () => {
    if (!state.project || document.hidden) return;
    const before = state.webapp && state.webapp.running;
    await refresh();
    const after = state.webapp && state.webapp.running;
    if (before && !after) {
      stopPolling();
      notify.warn('Сервер проекта остановился.');
      try {
        const { log } = await api.webappLogs(state.project.id);
        if (log) { dock.show('output'); runner.log(log); }
      } catch { /* не критично */ }
    }
  }, 5000);
}

function stopPolling() {
  clearInterval(pollTimer);
  pollTimer = null;
}

export function init() {
  // Кнопка #serverBtn подключается в main.js вместе с остальным хромом.
  on('project:selected', () => {
    stopPolling();
    paint(null);
    refresh().then(() => {
      if (state.webapp && state.webapp.running) startPolling();
    });
  });
}
