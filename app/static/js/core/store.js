/** Состояние приложения + простейшая шина событий. */

const bus = new Map();

export function on(event, handler) {
  if (!bus.has(event)) bus.set(event, new Set());
  bus.get(event).add(handler);
  return () => bus.get(event).delete(handler);
}

export function emit(event, payload) {
  (bus.get(event) || []).forEach((handler) => {
    try {
      handler(payload);
    } catch (error) {
      console.error(`[pyspace] обработчик ${event}:`, error);
    }
  });
}

export const state = {
  user: null,
  features: { registration: true, terminal: true, preview: true, persistent_storage: false },
  limits: { max_upload_mb: 200, max_file_kb: 4096, run_timeout: 20 },
  projects: [],
  project: null,       // {id, name, access, preview_token, ...}
  members: [],
  tree: [],            // плоский список узлов с сервера
  openFolders: new Set(),
  selectedPath: null,
  tabs: [],            // [{path, name, language, content, saved, dirty, binary, viewState}]
  activePath: null,
  dock: 'output',
  panel: 'explorer',
  previewOpen: false,
};

export const canWrite = () => state.project && state.project.access !== 'viewer';
export const isAdmin = () => Boolean(state.user && state.user.role === 'admin');

/** Локальные настройки (тема, размеры панелей, последний проект). */
const KEY = 'pyspace.prefs';

function readPrefs() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}');
  } catch {
    return {};
  }
}

export const prefs = {
  all: readPrefs(),
  get(name, fallback = null) {
    const value = this.all[name];
    return value === undefined ? fallback : value;
  },
  set(name, value) {
    this.all[name] = value;
    try {
      localStorage.setItem(KEY, JSON.stringify(this.all));
    } catch { /* приватный режим */ }
  },
};
