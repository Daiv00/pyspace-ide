/** Запуск кода и вывод результата в док. */
import api from '../core/api.js';
import { el, qs } from '../core/dom.js';
import { state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as dock from './dock.js';
import * as tabs from './tabs.js';

const RUNNABLE = /\.(py|sql)$/i;
const PREVIEWABLE = /\.(html|htm|css|js)$/i;

// Признаки веб-сервера: такие файлы запускаются в режиме сервера, а не скрипта,
// иначе процесс упирается в лимит времени и его гасят на середине работы.
const WEB_FRAMEWORKS = [
  { name: 'Flask', test: /^\s*[A-Za-z_]\w*\s*=\s*(?:flask\.)?Flask\s*\(/m },
  { name: 'FastAPI', test: /^\s*[A-Za-z_]\w*\s*=\s*(?:fastapi\.)?FastAPI\s*\(/m },
  { name: 'Uvicorn', test: /\buvicorn\.run\s*\(/ },
  { name: 'aiohttp', test: /\bweb\.run_app\s*\(/ },
  { name: 'http.server', test: /\bserve_forever\s*\(/ },
];

/** Текст без строк и комментариев: упоминание в комментарии — не запуск сервера. */
function codeOnly(source) {
  return source
    .replace(/["']{3}/g, '')
    .replace(/"[^"\n]*"|'[^'\n]*'/g, '""')
    .replace(/#[^\n]*/g, '');
}

/** Какой веб-фреймворк виден в тексте файла (или null). */
export function detectFramework(source = '') {
  if (!source) return null;
  const code = codeOnly(source);
  const found = WEB_FRAMEWORKS.find((item) => item.test.test(code));
  return found ? found.name : null;
}

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

  // Веб-сервер (Flask, FastAPI…) обычным запуском не поднять: он не завершается
  // сам и упирается в лимит времени. Переключаемся в режим сервера сами.
  if (/\.py$/i.test(path)) {
    let source = tabs.find(path)?.saved;
    if (source === undefined) {
      try {
        const { file } = await api.readFile(state.project.id, path);
        source = file.content || '';
      } catch { source = ''; }
    }
    const framework = detectFramework(source);
    if (framework) {
      const webapp = await import('./webapp.js');
      notify.info(`${framework}: переключился на режим сервера.`);
      await webapp.start(path, {
        note: `ℹ ${path}: похоже на веб-сервер (${framework}) — запускаю в режиме сервера без лимита времени.`,
      });
      return;
    }
  }

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
