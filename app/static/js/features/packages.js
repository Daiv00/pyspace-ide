/** Пакеты pip внутри проекта (папка .packages). */
import api from '../core/api.js';
import { clear, el, qs } from '../core/dom.js';
import { canWrite, state } from '../core/store.js';
import { notify } from '../core/toast.js';
import * as dock from './dock.js';
import * as runner from './runner.js';

export async function refresh() {
  const host = qs('#pipList');
  if (!host || !state.project) return;
  clear(host).append(el('div', { class: 'row' }, [
    el('span', { class: 'spinner' }), el('span', { class: 'muted', text: 'Читаем список…' }),
  ]));

  try {
    const { result } = await api.pipList(state.project.id);
    clear(host);
    let items = [];
    try {
      items = JSON.parse(result.output || '[]');
    } catch {
      items = [];
    }
    if (!items.length) {
      host.append(el('div', { class: 'empty' }, [
        el('strong', { text: 'Пакетов пока нет' }),
        'Установите первый — например, requests.',
      ]));
      return;
    }
    items
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((item) => {
        host.append(el('div', { class: 'package-row' }, [
          el('span', { text: item.name }),
          el('span', { text: item.version }),
        ]));
      });
  } catch (error) {
    clear(host).append(el('div', { class: 'empty', text: error.message }));
  }
}

export async function install(spec) {
  if (!state.project) { notify.warn('Выберите проект.'); return; }
  if (!canWrite()) { notify.warn('У вас доступ только для чтения.'); return; }
  const target = (spec || '').trim();
  if (!target) return;

  dock.show('output');
  runner.reset('');
  runner.log(`▶ pip install ${target}`, 'note');
  const pending = notify.info(`Устанавливаем ${target}…`);
  try {
    const { result } = await api.pipInstall(state.project.id, target);
    if (result.output) runner.log(result.output.trim());
    if (result.returncode === 0) {
      runner.log(`\n✓ Установлено: ${target}`, 'ok');
      notify.ok(`Пакет ${target} установлен.`);
      await refresh();
    } else {
      runner.log(`\n✕ pip завершился с кодом ${result.returncode}`, 'fail');
      notify.error('Установка не удалась — подробности в панели «Вывод».');
    }
  } catch (error) {
    runner.log(`\n✕ ${error.message}`, 'fail');
    notify.error(error.message);
  } finally {
    pending?.remove();
  }
}

export function init() {
  qs('#pipForm')?.addEventListener('submit', (event) => {
    event.preventDefault();
    const input = qs('#pipSpec');
    const value = input.value;
    input.value = '';
    install(value);
  });
  qs('#pipRefreshBtn')?.addEventListener('click', refresh);
}
