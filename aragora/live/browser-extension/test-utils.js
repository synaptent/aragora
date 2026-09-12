const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const EXTENSION_DIR = __dirname;

function readExtensionFile(name) {
  return fs.readFileSync(path.join(EXTENSION_DIR, name), 'utf8');
}

function loadPopupDocument() {
  document.documentElement.innerHTML = readExtensionFile('popup.html').replace(
    /<!doctype html>\s*/i,
    '',
  );
}

function createStorageArea(initialState, areaName, changeListeners) {
  let state = { ...initialState };

  return {
    async get(query) {
      if (typeof query === 'string') {
        return { [query]: state[query] };
      }

      if (Array.isArray(query)) {
        return Object.fromEntries(query.map((key) => [key, state[key]]));
      }

      if (query && typeof query === 'object') {
        return { ...query, ...state };
      }

      return { ...state };
    },

    async set(values) {
      const changes = Object.fromEntries(
        Object.entries(values).map(([key, value]) => [
          key,
          { oldValue: state[key], newValue: value },
        ]),
      );
      state = { ...state, ...values };

      for (const listener of changeListeners) {
        listener(changes, areaName);
      }
    },

    __getState() {
      return { ...state };
    },
  };
}

function createChromeMock(options = {}) {
  const listeners = {
    contextClicked: [],
    installed: [],
    messages: [],
    startup: [],
    storageChanged: [],
  };

  const chrome = {
    action: {
      setBadgeBackgroundColor: jest.fn(async () => undefined),
      setBadgeText: jest.fn(async () => undefined),
    },
    contextMenus: {
      create: jest.fn((_options, callback) => {
        if (callback) {
          callback();
        }
      }),
      onClicked: {
        addListener(listener) {
          listeners.contextClicked.push(listener);
        },
      },
      removeAll: jest.fn((callback) => {
        if (callback) {
          callback();
        }
      }),
    },
    runtime: {
      lastError: null,
      onInstalled: {
        addListener(listener) {
          listeners.installed.push(listener);
        },
      },
      onMessage: {
        addListener(listener) {
          listeners.messages.push(listener);
        },
      },
      onStartup: {
        addListener(listener) {
          listeners.startup.push(listener);
        },
      },
    },
    storage: {
      onChanged: {
        addListener(listener) {
          listeners.storageChanged.push(listener);
        },
      },
    },
    tabs: { sendMessage: jest.fn(async () => options.sendMessageResult ?? null) },
  };

  chrome.storage.local = createStorageArea(
    options.localState || {},
    'local',
    listeners.storageChanged,
  );
  chrome.storage.sync = createStorageArea(
    options.syncState || {},
    'sync',
    listeners.storageChanged,
  );
  chrome.__listeners = listeners;

  return chrome;
}

function loadExtensionScript(fileName, overrides = {}) {
  const chrome = overrides.chrome || createChromeMock();
  const fetchMock = overrides.fetchMock || jest.fn();
  const consoleMock = overrides.consoleMock || {
    error: jest.fn(),
    log: jest.fn(),
    warn: jest.fn(),
  };
  const targetWindow = overrides.window || window;
  const targetDocument = overrides.document || document;

  const context = {
    chrome,
    console: consoleMock,
    document: targetDocument,
    fetch: fetchMock,
    Promise,
    setInterval: targetWindow.setInterval.bind(targetWindow),
    setTimeout: targetWindow.setTimeout.bind(targetWindow),
    URL,
    window: targetWindow,
    clearInterval: targetWindow.clearInterval.bind(targetWindow),
    clearTimeout: targetWindow.clearTimeout.bind(targetWindow),
    Date,
  };
  context.global = context;
  context.globalThis = context;

  vm.createContext(context);
  vm.runInContext(readExtensionFile(fileName), context, { filename: fileName });

  return { chrome, consoleMock, context, fetchMock };
}

async function flushMicrotasks(turns = 8) {
  for (let index = 0; index < turns; index += 1) {
    await Promise.resolve();
  }
}

module.exports = {
  createChromeMock,
  flushMicrotasks,
  loadExtensionScript,
  loadPopupDocument,
  readExtensionFile,
};
