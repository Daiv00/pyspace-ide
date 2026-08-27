/** Единая точка обращения к REST API. Все ответы имеют вид {ok, ...}. */

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload || {};
  }
}

const listeners = new Set();

/** Подписка на индикатор занятости: cb(pendingCount). */
export function onBusy(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

let pending = 0;
function tick(delta) {
  pending = Math.max(0, pending + delta);
  listeners.forEach((cb) => cb(pending));
}

async function request(method, url, { json, form, signal } = {}) {
  const init = { method, headers: {}, signal, credentials: 'same-origin' };
  if (json !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(json);
  } else if (form) {
    init.body = form;
  }
  init.headers['X-Requested-With'] = 'pyspace';

  tick(1);
  let response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    tick(-1);
    if (error.name === 'AbortError') throw error;
    throw new ApiError('Нет связи с сервером. Проверьте соединение.', 0);
  }
  tick(-1);

  const type = response.headers.get('Content-Type') || '';
  if (!type.includes('application/json')) {
    if (!response.ok) throw new ApiError(`Ошибка сервера (${response.status}).`, response.status);
    return { ok: true };
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError('Сервер вернул некорректный ответ.', response.status);
  }

  if (!response.ok || payload.ok === false) {
    throw new ApiError(payload.error || `Ошибка ${response.status}.`, response.status, payload);
  }
  return payload;
}

const api = {
  get: (url, options) => request('GET', url, options),
  post: (url, json, options) => request('POST', url, { json, ...options }),
  put: (url, json, options) => request('PUT', url, { json, ...options }),
  patch: (url, json, options) => request('PATCH', url, { json, ...options }),
  del: (url, json, options) => request('DELETE', url, { json, ...options }),
  upload: (url, form, options) => request('POST', url, { form, ...options }),

  // --- Сессия ---
  session: () => api.get('/api/auth/session'),
  login: (username, password) => api.post('/api/auth/login', { username, password }),
  register: (username, password) => api.post('/api/auth/register', { username, password }),
  logout: () => api.post('/api/auth/logout', {}),
  changePassword: (current, next) => api.post('/api/auth/password', { current, password: next }),

  // --- Проекты ---
  projects: () => api.get('/api/projects'),
  createProject: (name, template) => api.post('/api/projects', { name, template }),
  project: (id) => api.get(`/api/projects/${id}`),
  renameProject: (id, name) => api.patch(`/api/projects/${id}`, { name }),
  deleteProject: (id) => api.del(`/api/projects/${id}`),
  addMember: (id, username, role) => api.post(`/api/projects/${id}/members`, { username, role }),
  removeMember: (id, userId) => api.del(`/api/projects/${id}/members/${userId}`),
  importZip: (form) => api.upload('/api/projects/import-zip', form),
  importZipInto: (id, form) => api.upload(`/api/projects/${id}/import-zip`, form),

  // --- Файлы ---
  tree: (id) => api.get(`/api/projects/${id}/tree`),
  readFile: (id, path) => api.get(`/api/projects/${id}/file?path=${encodeURIComponent(path)}`),
  saveFile: (id, path, content) => api.put(`/api/projects/${id}/file`, { path, content }),
  createEntry: (id, path, type, content = '') =>
    api.post(`/api/projects/${id}/file`, { path, type, content }),
  moveEntry: (id, from, to) => api.post(`/api/projects/${id}/move`, { from, to }),
  copyEntry: (id, from, to) => api.post(`/api/projects/${id}/copy`, { from, to }),
  deleteEntry: (id, path) => api.del(`/api/projects/${id}/file`, { path }),
  uploadFiles: (id, form) => api.upload(`/api/projects/${id}/upload`, form),
  searchFiles: (id, query, caseSensitive) =>
    api.get(`/api/projects/${id}/search?q=${encodeURIComponent(query)}&case=${caseSensitive ? 1 : 0}`),

  // --- Запуск ---
  run: (id, path, stdin) => api.post(`/api/projects/${id}/run`, { path, stdin }),
  pipInstall: (id, pkg) => api.post(`/api/projects/${id}/pip`, { package: pkg }),
  pipList: (id) => api.get(`/api/projects/${id}/pip`),
  terminalInfo: (id) => api.get(`/api/projects/${id}/terminal`),

  // --- Обмен ---
  drops: () => api.get('/api/drops'),
  createDrop: (label, projectId) => api.post('/api/drops', { label, project_id: projectId }),
  revokeDrop: (token) => api.post(`/api/drops/${token}/revoke`, {}),
  deleteDrop: (token) => api.del(`/api/drops/${token}`),
  dropInfo: (token) => api.get(`/api/drops/${token}`),
  dropUpload: (token, form) => api.upload(`/api/drops/${token}/upload`, form),
  vault: () => api.get('/api/drops/vault/files'),

  // --- Администрирование ---
  adminOverview: () => api.get('/api/admin/overview'),
  adminCreateUser: (username, password, role) =>
    api.post('/api/admin/users', { username, password, role }),
  adminUpdateUser: (id, patch) => api.patch(`/api/admin/users/${id}`, patch),
  adminDeleteUser: (id) => api.del(`/api/admin/users/${id}`),
  adminAssignFile: (fileId, userId) =>
    api.post(`/api/admin/vault/files/${fileId}/assign`, { user_id: userId }),
  adminDeleteFile: (fileId) => api.del(`/api/admin/vault/files/${fileId}`),

  // --- Обслуживание: самопинг и резервные копии ---
  maintenanceStatus: () => api.get('/api/maintenance/status'),
  maintenanceBackup: () => api.post('/api/maintenance/backup', {}),
  maintenanceRestore: () => api.post('/api/maintenance/restore', {}),
};

export default api;
