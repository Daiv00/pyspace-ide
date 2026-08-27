/** Обёртка над Monaco: модели по путям, темы, горячие клавиши, статус курсора. */
import { qs } from '../core/dom.js';
import { emit, prefs, state } from '../core/store.js';

let editor = null;
let monacoRef = null;
const models = new Map();     // path -> ITextModel
const viewStates = new Map();  // path -> ICodeEditorViewState
let readyResolve;
export const ready = new Promise((resolve) => { readyResolve = resolve; });

const THEME_DARK = {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '5f6b80', fontStyle: 'italic' },
    { token: 'keyword', foreground: 'a394ff' },
    { token: 'string', foreground: '8ee0a8' },
    { token: 'number', foreground: 'f0b429' },
    { token: 'type', foreground: '6ec9ff' },
    { token: 'function', foreground: '9fd0ff' },
  ],
  colors: {
    'editor.background': '#0b0d12',
    'editor.foreground': '#e9edf6',
    'editorLineNumber.foreground': '#3c4557',
    'editorLineNumber.activeForeground': '#8b7cff',
    'editor.selectionBackground': '#8b7cff33',
    'editor.lineHighlightBackground': '#12151d',
    'editorCursor.foreground': '#8b7cff',
    'editorIndentGuide.background1': '#1c212c',
    'editorIndentGuide.activeBackground1': '#2b3242',
    'editorWidget.background': '#12151d',
    'editorWidget.border': '#262c3a',
    'editorSuggestWidget.selectedBackground': '#8b7cff2a',
    'scrollbarSlider.background': '#1e233066',
  },
};

const THEME_LIGHT = {
  base: 'vs',
  inherit: true,
  rules: [
    { token: 'comment', foreground: '7b869b', fontStyle: 'italic' },
    { token: 'keyword', foreground: '5f45d8' },
  ],
  colors: {
    'editor.background': '#ffffff',
    'editor.foreground': '#131722',
    'editorLineNumber.foreground': '#a6b0c3',
    'editorLineNumber.activeForeground': '#6a54f5',
    'editor.lineHighlightBackground': '#f4f6fb',
    'editorCursor.foreground': '#6a54f5',
  },
};

const BASE_OPTIONS = {
  automaticLayout: true,
  fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
  fontLigatures: false,
  fontSize: 14,
  lineHeight: 22,
  tabSize: 4,
  insertSpaces: true,
  minimap: { enabled: true, renderCharacters: false, maxColumn: 90 },
  scrollBeyondLastLine: false,
  smoothScrolling: true,
  cursorSmoothCaretAnimation: 'on',
  cursorBlinking: 'smooth',
  renderWhitespace: 'selection',
  bracketPairColorization: { enabled: true },
  guides: { bracketPairs: true, indentation: true },
  padding: { top: 12, bottom: 60 },
  scrollbar: { verticalScrollbarSize: 11, horizontalScrollbarSize: 11, useShadows: false },
  suggestSelection: 'first',
  wordWrap: 'off',
  stickyScroll: { enabled: true },
  linkedEditing: true,
  formatOnPaste: true,
  contextmenu: true,
};

export function themeName() {
  return document.documentElement.dataset.theme === 'light' ? 'pyspace-light' : 'pyspace-dark';
}

export function applyTheme() {
  if (monacoRef) monacoRef.editor.setTheme(themeName());
}

/** Загружает Monaco через AMD-загрузчик из CDN. */
export function init() {
  return new Promise((resolve, reject) => {
    if (!window.require) {
      reject(new Error('Не удалось загрузить редактор Monaco (проверьте доступ к CDN).'));
      return;
    }
    window.require.config({
      paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs' },
      'vs/nls': { availableLanguages: { '*': 'ru' } },
    });
    window.require(['vs/editor/editor.main'], () => {
      monacoRef = window.monaco;
      monacoRef.editor.defineTheme('pyspace-dark', THEME_DARK);
      monacoRef.editor.defineTheme('pyspace-light', THEME_LIGHT);

      editor = monacoRef.editor.create(qs('#monaco'), {
        ...BASE_OPTIONS,
        fontSize: prefs.get('fontSize', 14),
        wordWrap: prefs.get('wordWrap', 'off'),
        minimap: { ...BASE_OPTIONS.minimap, enabled: prefs.get('minimap', true) },
        theme: themeName(),
        value: '',
        language: 'plaintext',
      });

      editor.onDidChangeModelContent(() => {
        const path = state.activePath;
        if (!path) return;
        const tab = state.tabs.find((item) => item.path === path);
        if (!tab) return;
        const dirty = editor.getValue() !== tab.saved;
        if (dirty !== tab.dirty) {
          tab.dirty = dirty;
          emit('tabs:changed');
        }
      });

      editor.onDidChangeCursorPosition((event) => {
        const status = qs('#statusCursor');
        if (status) status.textContent = `Стр ${event.position.lineNumber}, Кол ${event.position.column}`;
      });

      readyResolve(editor);
      resolve(editor);
    }, reject);
  });
}

export const instance = () => editor;
export const monaco = () => monacoRef;

/** Показывает файл в редакторе, создавая модель при необходимости. */
export function show(path, content, language) {
  if (!editor) return;
  let model = models.get(path);
  if (!model) {
    model = monacoRef.editor.createModel(
      content,
      language || 'plaintext',
      monacoRef.Uri.parse(`inmemory://project/${encodeURI(path)}`),
    );
    models.set(path, model);
  } else if (content !== undefined && model.getValue() !== content) {
    model.setValue(content);
  }
  const previous = state.activePath;
  if (previous && editor.getModel()) viewStates.set(previous, editor.saveViewState());

  editor.setModel(model);
  const saved = viewStates.get(path);
  if (saved) editor.restoreViewState(saved);
  editor.updateOptions({ readOnly: !isWritable() });
  editor.focus();
}

function isWritable() {
  return Boolean(state.project && state.project.access !== 'viewer');
}

export function refreshReadOnly() {
  editor?.updateOptions({ readOnly: !isWritable() });
}

export function value() {
  return editor ? editor.getValue() : '';
}

export function setValue(text) {
  editor?.getModel()?.setValue(text);
}

export function dispose(path) {
  const model = models.get(path);
  if (model) { model.dispose(); models.delete(path); }
  viewStates.delete(path);
}

export function disposeAll() {
  models.forEach((model) => model.dispose());
  models.clear();
  viewStates.clear();
  editor?.setModel(null);
}

export function detachModel() {
  editor?.setModel(null);
}

export function setOption(name, value) {
  if (!editor) return;
  if (name === 'minimap') editor.updateOptions({ minimap: { ...BASE_OPTIONS.minimap, enabled: value } });
  else editor.updateOptions({ [name]: value });
  prefs.set(name, value);
}

export function getOption(name, fallback) {
  return prefs.get(name, fallback);
}

export function action(id) {
  editor?.getAction(id)?.run();
}

export function goTo(line, column = 1) {
  if (!editor) return;
  editor.revealLineInCenter(line);
  editor.setPosition({ lineNumber: line, column });
  editor.focus();
}

export function layout() {
  editor?.layout();
}
