/** Запуск кода и вывод результата в док. */
import api from '../core/api.js';
import { el, qs } from '../core/dom.js';
import { state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as dock from './dock.js';
import * as tabs from './tabs.js';

const RUNNABLE = /\.(py|sql)$/i;
const PREVIEWABLE = /\.(html|htm|css|js)$/i;

let running = false;

export function log(text, kind = '') {
  const box = qs('#outputLog');
  if (!box) return;
  const line = kind ? el('span', { class: kind, text: `${text}\n` }) : document.createTextNode(`${text}\n`);
  box.append(line);
  box.scrollTop = box.scrollHeight;
}

export function reset(text = '') {
  const box = qs('#outputLog');
  if (box) box.textContent = text;
  const meta = qs('#runMeta');
  if (meta) meta.textContent = '';
}

function setBusy(busy) {
  running = busy;
  const button = qs('#runBtn');
  if (button) button.disabled = busy;
  const dot = qs('#connDot');
  const text = qs('#connText');
  if (dot) dot.dataset.state = busy ? 'busy' : 'ok';
  if (text) text.textContent = busy ? 'выполняется…' : 'готов';
}

/** Запускает активный файл (или указанный путь). */
export async function run(path = state.activePath) {
  if (running) { notify.warn('Программа ещё выполняется.'); return; }
  if (!state.project) { notify.warn('Выберите проект.'); return; }
  if (!path) { notify.warn('Откройте файл, который нужно запустить.'); return; }

  if (PREVIEWABLE.test(path) && !RUNNABLE.test(path)) {
    const preview = await import('./preview.js');
    await tabs.save(path, { silent: true });
    preview.open(path);
    return;
  }
  if (!RUNNABLE.test(path)) {
    notify.warn('Запускаются файлы .py и .sql. HTML/CSS/JS открываются в предпросмотре.');
    return;
  }

  await tabs.save(path, { silent: true });
  dock.show('output');
  dock.expand();
  reset('');
  log(`▶ ${path}`, 'note');
  setBusy(true);

  try {
    const { result } = await api.run(state.project.id, path, qs('#stdinBox')?.value || '');
    const output = String(result.output ?? '').replace(/\n$/, '');
    if (output) log(output);
    const meta = qs('#runMeta');
    const seconds = ((result.duration_ms || 0) / 1000).toFixed(2);
    if (meta) meta.textContent = `код ${result.returncode} · ${seconds} с`;
    if (result.timed_out) {
      log(`\n⏱ Превышен лимит ${state.limits.run_timeout} с — процесс остановлен.`, 'fail');
    } else if (result.returncode === 0) {
      log(`\n✓ Готово за ${seconds} с`, 'ok');
    } else {
      log(`\n✕ Завершено с кодом ${result.returncode}`, 'fail');
    }
  } catch (error) {
    log(`\n✕ ${error.message}`, 'fail');
    notify.error(error.message);
  } finally {
    setBusy(false);
  }
}

export const isRunning = () => running;
