/** Нижняя панель: переключение «Вывод / Терминал», свёртка, очистка. */
import { qsa, qs } from '../core/dom.js';
import { emit, prefs, state } from '../core/store.js';

export function show(name) {
  state.dock = name;
  qsa('.dock-tab').forEach((tab) => tab.setAttribute('aria-selected', tab.dataset.dock === name ? 'true' : 'false'));
  qsa('.dock-pane').forEach((pane) => {
    if (pane.dataset.dock === name) pane.dataset.active = 'true';
    else delete pane.dataset.active;
  });
  expand();
  emit('dock:shown', name);
}

export function expand() {
  const dock = qs('#dock');
  if (!dock) return;
  dock.dataset.collapsed = 'false';
  prefs.set('dockCollapsed', false);
  syncToggle();
  emit('dock:resized');
}

export function collapse() {
  const dock = qs('#dock');
  if (!dock) return;
  dock.dataset.collapsed = 'true';
  prefs.set('dockCollapsed', true);
  syncToggle();
  emit('dock:resized');
}

export function toggle() {
  const dock = qs('#dock');
  if (!dock) return;
  if (dock.dataset.collapsed === 'true') expand();
  else collapse();
}

function syncToggle() {
  const dock = qs('#dock');
  const button = qs('#dockToggleBtn');
  if (!dock || !button) return;
  const collapsed = dock.dataset.collapsed === 'true';
  button.textContent = collapsed ? '▴' : '▾';
  button.title = collapsed ? 'Развернуть панель' : 'Свернуть панель';
}

export function init() {
  qsa('.dock-tab').forEach((tab) => {
    tab.addEventListener('click', () => show(tab.dataset.dock));
  });
  qs('#dockToggleBtn')?.addEventListener('click', toggle);
  if (prefs.get('dockCollapsed', false)) collapse();
  else syncToggle();
  show(prefs.get('dockTab', 'output'));
}
