/** Вход, регистрация, меню пользователя. */
import api from '../core/api.js';
import { el, qs, qsa } from '../core/dom.js';
import { openSheet, showMenu } from '../core/modal.js';
import { emit, state } from '../core/store.js';
import { notify } from '../core/toast.js';

let mode = 'login';

function setStatus(text, kind = '') {
  const node = qs('#authStatus');
  if (!node) return;
  node.textContent = text;
  node.dataset.kind = kind;
}

function setMode(next) {
  mode = next;
  qsa('[data-auth-mode]').forEach((tab) => {
    tab.setAttribute('aria-selected', tab.dataset.authMode === next ? 'true' : 'false');
  });
  const submit = qs('#authSubmit');
  if (submit) submit.textContent = next === 'login' ? 'Войти' : 'Создать аккаунт';
  const password = qs('#authPass');
  if (password) password.autocomplete = next === 'login' ? 'current-password' : 'new-password';
  setStatus('');
}

export function showGate() {
  qs('#gate').hidden = false;
  qs('#app').hidden = true;
  const registration = state.features.registration;
  const tab = qs('#authRegisterTab');
  if (tab) tab.hidden = !registration;
  const note = qs('#authNote');
  if (note) {
    note.textContent = registration
      ? 'Первый зарегистрированный пользователь становится администратором.'
      : 'Регистрация закрыта — попросите администратора создать аккаунт.';
  }
  if (!registration) setMode('login');
  setTimeout(() => qs('#authUser')?.focus(), 60);
}

export function showApp() {
  qs('#gate').hidden = true;
  qs('#app').hidden = false;
  const name = qs('#userName');
  const avatar = qs('#userAvatar');
  if (name) name.textContent = state.user.username;
  if (avatar) avatar.textContent = state.user.username.slice(0, 1).toUpperCase();
  qs('#adminRail')?.classList.toggle('is-hidden', state.user.role !== 'admin');
  const storage = qs('#statusStorage');
  if (storage) {
    storage.textContent = state.features.persistent_storage ? 'диск: постоянный' : 'диск: временный';
    storage.title = state.features.persistent_storage
      ? 'Данные сохраняются между перезапусками.'
      : 'Внимание: на бесплатном плане Render файлы исчезают при редеплое.';
  }
}

async function submit(event) {
  event.preventDefault();
  const username = qs('#authUser').value.trim();
  const password = qs('#authPass').value;
  if (!username || !password) { setStatus('Заполните оба поля.', 'error'); return; }

  const button = qs('#authSubmit');
  button.disabled = true;
  setStatus(mode === 'login' ? 'Проверяем…' : 'Создаём аккаунт…');
  try {
    const result = mode === 'login'
      ? await api.login(username, password)
      : await api.register(username, password);
    state.user = result.user;
    setStatus('Готово.', 'success');
    if (result.first_admin) notify.ok('Вы первый пользователь — права администратора выданы.');
    emit('auth:signed-in', result.user);
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

export async function logout() {
  try {
    await api.logout();
  } catch { /* всё равно выходим */ }
  location.reload();
}

export function openPasswordChange() {
  const current = el('input', { class: 'input', type: 'password', autocomplete: 'current-password' });
  const next = el('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
  const submitPassword = async () => {
    try {
      const result = await api.changePassword(current.value, next.value);
      notify.ok(result.message || 'Пароль обновлён.');
      dialog.close();
    } catch (error) { notify.error(error.message); }
  };
  const dialog = openSheet({
    title: 'Смена пароля',
    size: 'narrow',
    body: [
      el('div', { class: 'field' }, [el('label', { text: 'Текущий пароль' }), current]),
      el('div', { class: 'field' }, [el('label', { text: 'Новый пароль (минимум 8 символов)' }), next]),
    ],
    actions: [
      el('button', { class: 'btn', text: 'Отмена', onClick: () => dialog.close() }),
      el('button', { class: 'btn btn--primary', text: 'Сохранить', onClick: submitPassword }),
    ],
  });
}

export function openUserMenu(anchor) {
  showMenu([
    { heading: `${state.user.username} · ${state.user.role === 'admin' ? 'администратор' : 'пользователь'}` },
    { label: 'Сменить пароль…', icon: '🔑', onSelect: openPasswordChange },
    { separator: true },
    { label: 'Выйти', icon: '⎋', danger: true, onSelect: logout },
  ], { anchor, align: 'end' });
}

export function init() {
  qs('#authForm')?.addEventListener('submit', submit);
  qsa('[data-auth-mode]').forEach((tab) => {
    tab.addEventListener('click', () => setMode(tab.dataset.authMode));
  });
  qs('#userBtn')?.addEventListener('click', (event) => openUserMenu(event.currentTarget));
  setMode('login');
}
