/** Палитра команд: Ctrl+K (команды) и Ctrl+P (файлы проекта). */
import { clear, el } from './dom.js';
import { openSheet } from './modal.js';

const commands = [];

/** register({id, title, group, icon, hint, when, run}) */
export function register(command) {
  commands.push(command);
}

export function registerAll(list) {
  list.forEach(register);
}

/** Нечёткое совпадение: все символы запроса встречаются по порядку. */
function fuzzyScore(text, query) {
  if (!query) return 1;
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase();
  if (haystack.includes(needle)) return 1000 - haystack.indexOf(needle);
  let score = 0;
  let index = 0;
  for (const ch of needle) {
    const found = haystack.indexOf(ch, index);
    if (found < 0) return 0;
    score += found === index ? 3 : 1;
    index = found + 1;
  }
  return score;
}

export function openPalette({ mode = 'commands', items = null, placeholder = '' } = {}) {
  const source = items || commands.filter((command) => !command.when || command.when());
  const input = el('input', {
    class: 'palette__input',
    placeholder: placeholder || (mode === 'files' ? 'Найти файл по имени…' : 'Введите команду…'),
    autocomplete: 'off',
    spellcheck: 'false',
  });
  const list = el('div', { class: 'palette__list', role: 'listbox' });

  let visible = [];
  let cursor = 0;

  function render() {
    const query = input.value.trim();
    visible = source
      .map((item) => ({ item, score: fuzzyScore(`${item.title} ${item.group || ''}`, query) }))
      .filter((entry) => entry.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 60)
      .map((entry) => entry.item);

    cursor = 0;
    clear(list);
    if (!visible.length) {
      list.append(el('div', { class: 'empty', text: 'Ничего не найдено' }));
      return;
    }
    visible.forEach((item, index) => {
      list.append(el('button', {
        class: 'palette__item',
        type: 'button',
        role: 'option',
        dataset: { cursor: index === cursor ? 'true' : 'false', index },
        onMouseEnter: () => moveTo(index),
        onClick: () => choose(index),
      }, [
        el('span', { class: 'palette__icon', text: item.icon || '›' }),
        el('span', { class: 'grow truncate', text: item.title }),
        item.hint ? el('kbd', { text: item.hint }) : null,
        item.group ? el('span', { class: 'palette__group', text: item.group }) : null,
      ]));
    });
  }

  function moveTo(index) {
    if (!visible.length) return;
    cursor = (index + visible.length) % visible.length;
    Array.from(list.children).forEach((node, position) => {
      if (node.dataset) node.dataset.cursor = position === cursor ? 'true' : 'false';
    });
    list.children[cursor]?.scrollIntoView({ block: 'nearest' });
  }

  function choose(index) {
    const item = visible[index === undefined ? cursor : index];
    if (!item) return;
    dialog.close();
    setTimeout(() => item.run(), 0);
  }

  input.addEventListener('input', render);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); moveTo(cursor + 1); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); moveTo(cursor - 1); }
    else if (event.key === 'Enter') { event.preventDefault(); choose(); }
  });

  const dialog = openSheet({ title: '', size: 'narrow' });
  clear(dialog.sheet);
  dialog.sheet.classList.add('palette');
  dialog.sheet.append(input, list);
  render();
  setTimeout(() => input.focus(), 20);
  return dialog;
}
