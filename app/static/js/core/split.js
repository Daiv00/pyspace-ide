/** Перетаскиваемые разделители панелей. */
import { prefs } from './store.js';

/**
 * makeGutter(handle, {axis, variable, min, max, invert, key, onMove})
 * Пишет значение в CSS-переменную на :root и запоминает его в настройках.
 */
export function makeGutter(handle, {
  axis = 'x',
  variable,
  min = 160,
  max = () => 640,
  invert = false,
  key = null,
  onMove = null,
} = {}) {
  if (!handle) return;

  const root = document.documentElement;
  const saved = key ? prefs.get(key) : null;
  if (saved) root.style.setProperty(variable, `${saved}px`);

  const limitMax = typeof max === 'function' ? max : () => max;

  let start = 0;
  let base = 0;

  function current() {
    const value = getComputedStyle(root).getPropertyValue(variable).trim();
    return parseFloat(value) || min;
  }

  function down(event) {
    if (event.button !== undefined && event.button !== 0) return;
    event.preventDefault();
    handle.dataset.dragging = 'true';
    document.body.style.userSelect = 'none';
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
    start = axis === 'x' ? event.clientX : event.clientY;
    base = current();
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up, { once: true });
  }

  function move(event) {
    const now = axis === 'x' ? event.clientX : event.clientY;
    const delta = (now - start) * (invert ? -1 : 1);
    const value = Math.max(min, Math.min(base + delta, limitMax()));
    root.style.setProperty(variable, `${Math.round(value)}px`);
    onMove?.(value);
  }

  function up() {
    delete handle.dataset.dragging;
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
    window.removeEventListener('pointermove', move);
    if (key) prefs.set(key, Math.round(current()));
    onMove?.(current());
  }

  handle.addEventListener('pointerdown', down);
  handle.addEventListener('dblclick', () => {
    root.style.removeProperty(variable);
    if (key) prefs.set(key, null);
    onMove?.(current());
  });
}
