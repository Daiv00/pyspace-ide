/** Настоящий терминал: xterm.js поверх WebSocket-канала к PTY проекта. */
import { clear, el, qs } from '../core/dom.js';
import { on, prefs, state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as dock from './dock.js';

let term = null;
let fit = null;
let socket = null;
let projectId = null;
let pingTimer = null;
let reconnects = 0;
let intentionalClose = false;

const THEMES = {
  dark: {
    background: '#070810', foreground: '#e9edf6', cursor: '#8b7cff', cursorAccent: '#070810',
    selectionBackground: '#8b7cff44',
    black: '#1a1e28', red: '#f5717f', green: '#45d483', yellow: '#f0b429',
    blue: '#5b8cff', magenta: '#a394ff', cyan: '#4cc2ff', white: '#c8d0e0',
    brightBlack: '#545e70', brightRed: '#ff8a95', brightGreen: '#6ee49b', brightYellow: '#ffca4d',
    brightBlue: '#7ea6ff', brightMagenta: '#bcb0ff', brightCyan: '#7ad4ff', brightWhite: '#f2f5fa',
  },
  light: {
    background: '#ffffff', foreground: '#131722', cursor: '#6a54f5', cursorAccent: '#ffffff',
    selectionBackground: '#6a54f533',
    black: '#131722', red: '#d93a4d', green: '#16a45c', yellow: '#b57500',
    blue: '#1657d8', magenta: '#6a54f5', cyan: '#0d7fbf', white: '#4b5468',
    brightBlack: '#7b869b', brightRed: '#f5717f', brightGreen: '#2fb970', brightYellow: '#d08c00',
    brightBlue: '#3b74ee', brightMagenta: '#8b7cff', brightCyan: '#1f9ed8', brightWhite: '#131722',
  },
};

function setState(text, kind = '') {
  const chip = qs('#terminalState');
  if (!chip) return;
  chip.textContent = text;
  chip.className = `chip ${kind ? `chip--${kind}` : ''}`;
  const dot = qs('#terminalDot');
  if (dot) dot.classList.toggle('is-hidden', kind !== 'success');
}

export function applyTheme() {
  if (!term) return;
  term.options.theme = document.documentElement.dataset.theme === 'light' ? THEMES.light : THEMES.dark;
}

function ensureTerm() {
  if (term) return true;
  const host = qs('#terminalHost');
  if (!host) return false;
  if (!window.Terminal) {
    clear(host).append(el('div', { class: 'terminal-offline' }, [
      el('strong', { text: 'Библиотека терминала не загрузилась' }),
      el('p', { class: 'muted', text: 'Проверьте доступ к CDN jsdelivr и обновите страницу.' }),
    ]));
    return false;
  }

  term = new window.Terminal({
    fontFamily: '"JetBrains Mono", ui-monospace, Menlo, Consolas, monospace',
    fontSize: prefs.get('terminalFontSize', 13),
    lineHeight: 1.25,
    cursorBlink: true,
    cursorStyle: 'bar',
    scrollback: 6000,
    convertEol: false,
    allowProposedApi: true,
    theme: document.documentElement.dataset.theme === 'light' ? THEMES.light : THEMES.dark,
  });

  if (window.FitAddon) {
    fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
  }
  if (window.WebLinksAddon) term.loadAddon(new window.WebLinksAddon.WebLinksAddon());

  clear(host);
  term.open(host);
  resize();

  term.onData((data) => send({ type: 'input', data }));
  term.onResize(({ cols, rows }) => send({ type: 'resize', cols, rows }));
  return true;
}

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
    return true;
  }
  return false;
}

export function resize() {
  if (!term || !fit) return;
  const host = qs('#terminalHost');
  if (!host || !host.clientHeight) return;
  try {
    fit.fit();
  } catch { /* панель ещё скрыта */ }
}

/** Подключиться к терминалу текущего проекта. */
export function connect({ force = false } = {}) {
  if (!state.project) { notify.warn('Сначала откройте проект.'); return; }
  if (!state.features.terminal) { setState('отключён администратором', 'warn'); return; }
  if (state.project.access === 'viewer') { setState('только чтение', 'warn'); return; }
  if (!ensureTerm()) return;

  if (socket && socket.readyState <= WebSocket.OPEN && projectId === state.project.id && !force) {
    resize();
    return;
  }
  disconnect({ quiet: true });

  projectId = state.project.id;
  intentionalClose = false;
  setState('подключение…', 'warn');

  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${scheme}://${location.host}/ws/terminal/${projectId}`);

  socket.onopen = () => {
    reconnects = 0;
    send({ cols: term.cols, rows: term.rows });
    pingTimer = setInterval(() => send({ type: 'ping' }), 25000);
  };

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      term.write(event.data);
      return;
    }
    if (message.type === 'output') term.write(message.data);
    else if (message.type === 'ready') {
      setState(`bash · ${message.cwd || 'проект'}`, 'success');
      resize();
    } else if (message.type === 'exit') {
      setState('сеанс завершён', 'warn');
      term.write(`\r\n\x1b[90m— сеанс завершён (код ${message.code ?? 0}). Нажмите «Перезапустить».\x1b[0m\r\n`);
    } else if (message.type === 'error') {
      setState('ошибка', 'danger');
      term.write(`\r\n\x1b[31m${message.message}\x1b[0m\r\n`);
      if (message.fatal) intentionalClose = true;
    }
  };

  socket.onclose = () => {
    clearInterval(pingTimer);
    if (intentionalClose) { setState('отключён'); return; }
    setState('соединение потеряно', 'danger');
    if (reconnects < 3 && qs('#dock')?.dataset.collapsed !== 'true') {
      reconnects += 1;
      setTimeout(() => connect({ force: true }), 900 * reconnects);
    }
  };

  socket.onerror = () => setState('ошибка соединения', 'danger');
}

export function disconnect({ quiet = false } = {}) {
  clearInterval(pingTimer);
  intentionalClose = true;
  if (socket) {
    try { send({ type: 'close' }); socket.close(); } catch { /* уже закрыт */ }
    socket = null;
  }
  if (!quiet) setState('отключён');
}

export function restart() {
  if (term) term.reset();
  reconnects = 0;
  connect({ force: true });
}

export function interrupt() {
  if (!send({ type: 'signal', name: 'SIGINT' })) notify.warn('Терминал не подключён.');
}

export function focus() {
  term?.focus();
}

/** Отправить команду в терминал (используется палитрой команд). */
export function runCommand(command) {
  dock.show('terminal');
  connect();
  setTimeout(() => send({ type: 'input', data: `${command}\n` }), 350);
}

export function init() {
  qs('#terminalRestart')?.addEventListener('click', restart);
  qs('#terminalInterrupt')?.addEventListener('click', interrupt);
  setState('отключён');

  on('dock:shown', (name) => {
    if (name === 'terminal') { connect(); setTimeout(() => { resize(); focus(); }, 60); }
  });
  on('dock:resized', () => setTimeout(resize, 60));
  on('project:selected', () => {
    if (socket) { disconnect({ quiet: true }); term?.reset(); setState('отключён'); }
  });
  window.addEventListener('resize', () => setTimeout(resize, 80));
  window.addEventListener('beforeunload', () => disconnect({ quiet: true }));
}
