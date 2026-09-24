const STATE_KEY = 'aragoraPopupState';
const DEFAULT_SETTINGS = {
  apiUrl: 'https://api.aragora.ai',
  apiKey: '',
  agents: '',
  rounds: 3,
  consensus: 'majority',
};
const TERMINAL_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
  'error',
  'done',
  'consensus_reached',
]);

const elements = {};
let pollTimer = null;

function normalizeApiUrl(apiUrl) {
  return String(apiUrl || DEFAULT_SETTINGS.apiUrl)
    .trim()
    .replace(/\/+$/, '');
}

function buildAuthorizationHeader(apiKey) {
  const trimmed = String(apiKey || '').trim();
  if (!trimmed) {
    return '';
  }

  return /^Bearer\s+/i.test(trimmed) ? trimmed : `Bearer ${trimmed}`;
}

function humanizeStatus(status) {
  const normalized = String(status || 'idle')
    .trim()
    .toLowerCase();

  switch (normalized) {
    case 'submitting':
      return 'Submitting';
    case 'running':
      return 'Running';
    case 'completed':
    case 'consensus_reached':
      return 'Completed';
    case 'failed':
    case 'error':
      return 'Error';
    default:
      return normalized ? normalized[0].toUpperCase() + normalized.slice(1) : 'Idle';
  }
}

function isTerminalState(state) {
  const normalized = String(state?.status || '').toLowerCase();
  return TERMINAL_STATUSES.has(normalized) || Boolean(resolveFinalAnswer(state?.result));
}

function resolveFinalAnswer(result) {
  return (
    result?.conclusion ||
    result?.final_answer ||
    result?.finalAnswer ||
    result?.answer ||
    result?.summary ||
    result?.consensus?.conclusion ||
    result?.consensus?.final_answer ||
    result?.consensus?.finalAnswer ||
    result?.consensus?.summary ||
    result?.consensus?.answer ||
    ''
  );
}

function resolveConfidence(result) {
  const rawConfidence =
    result?.confidence ?? result?.consensus?.confidence ?? result?.consensus?.agreement;
  const confidence = typeof rawConfidence === 'string' ? Number(rawConfidence) : rawConfidence;

  return typeof confidence === 'number' && !Number.isNaN(confidence) ? confidence : null;
}

async function getStoredState() {
  const stored = await chrome.storage.local.get(STATE_KEY);
  return stored[STATE_KEY] || null;
}

function setStatusPill(status) {
  const normalized = String(status || 'idle').toLowerCase();
  elements.statusPill.textContent = humanizeStatus(status);
  elements.statusPill.className = 'status-pill';

  if (normalized === 'submitting' || normalized === 'running') {
    elements.statusPill.classList.add(`is-${normalized}`);
    return;
  }

  if (normalized === 'completed' || normalized === 'consensus_reached') {
    elements.statusPill.classList.add('is-completed');
    return;
  }

  if (normalized === 'error' || normalized === 'failed') {
    elements.statusPill.classList.add('is-error');
    return;
  }

  elements.statusPill.classList.add('is-idle');
}

function renderSource(source) {
  if (source?.pageUrl) {
    elements.sourceLink.href = source.pageUrl;
    elements.sourceLink.textContent = source.pageTitle || 'Open source page';
    elements.sourceLink.classList.remove('hidden');
    return;
  }

  elements.sourceLink.href = '#';
  elements.sourceLink.textContent = '';
  elements.sourceLink.classList.add('hidden');
}

function renderError(errorMessage) {
  if (!errorMessage) {
    elements.resultError.textContent = '';
    elements.resultError.classList.add('hidden');
    return;
  }

  elements.resultError.textContent = errorMessage;
  elements.resultError.classList.remove('hidden');
}

function renderState(state) {
  const activeState = state || {};
  const result = activeState.result || {};
  setStatusPill(activeState.status || 'idle');

  elements.selectionPreview.textContent = activeState.selectionText || 'No text has been sent yet.';
  renderSource(activeState.source);

  elements.debateId.textContent = activeState.debateId || '-';
  elements.resultStatus.textContent = humanizeStatus(result.status || activeState.status || 'idle');

  const confidence = resolveConfidence(result);
  elements.resultConfidence.textContent =
    typeof confidence === 'number' && !Number.isNaN(confidence)
      ? `${Math.round(confidence * 100)}%`
      : '-';

  const answer =
    resolveFinalAnswer(result) ||
    result.message ||
    (activeState.status === 'submitting'
      ? 'Submitting selection to Aragora.'
      : activeState.status === 'running'
        ? 'Debate is still running. Keep this popup open or refresh.'
        : 'No result yet.');
  elements.resultAnswer.textContent = answer;

  renderError(activeState.error);
}

function populateSettings(settings) {
  elements.apiUrl.value = settings.apiUrl || DEFAULT_SETTINGS.apiUrl;
  elements.apiKey.value = settings.apiKey || '';
  elements.agents.value = settings.agents || '';
  elements.rounds.value = String(settings.rounds || DEFAULT_SETTINGS.rounds);
}

async function saveSettings() {
  const nextSettings = {
    apiUrl: elements.apiUrl.value.trim() || DEFAULT_SETTINGS.apiUrl,
    apiKey: elements.apiKey.value.trim(),
    agents: elements.agents.value.trim(),
    rounds: Math.min(20, Math.max(1, Number(elements.rounds.value) || DEFAULT_SETTINGS.rounds)),
    consensus: DEFAULT_SETTINGS.consensus,
  };

  await chrome.storage.sync.set(nextSettings);
  populateSettings(nextSettings);

  elements.settingsStatus.textContent = 'Saved';
  window.setTimeout(() => {
    if (elements.settingsStatus.textContent === 'Saved') {
      elements.settingsStatus.textContent = '';
    }
  }, 1200);
}

async function readErrorMessage(response) {
  const fallback = `Request failed with status ${response.status}`;

  try {
    const body = await response.json();
    return body.detail || body.error || body.message || fallback;
  } catch {
    try {
      const text = await response.text();
      return text || fallback;
    } catch {
      return fallback;
    }
  }
}

async function fetchDebate(apiUrl, apiKey, debateId) {
  const response = await fetch(`${normalizeApiUrl(apiUrl)}/api/v2/debates/${debateId}`, {
    headers: {
      'Content-Type': 'application/json',
      Authorization: buildAuthorizationHeader(apiKey),
    },
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

function buildResultState(previousState, debate) {
  const confidence = resolveConfidence(debate);
  const nextStatus = String(debate?.status || previousState.status || 'running').toLowerCase();
  const finalAnswer = resolveFinalAnswer(debate);

  return {
    ...previousState,
    status: nextStatus,
    error: null,
    result: {
      debateId: debate.id || debate.debate_id || previousState.debateId,
      status: debate.status || previousState.status || 'running',
      finalAnswer,
      confidence,
      task: debate.task || debate.environment?.task || '',
    },
    updatedAt: new Date().toISOString(),
  };
}

async function refreshDebateState() {
  const [settings, state] = await Promise.all([
    chrome.storage.sync.get(DEFAULT_SETTINGS),
    getStoredState(),
  ]);

  if (!state?.debateId) {
    renderState(state);
    return;
  }

  if (!String(settings.apiKey || '').trim()) {
    renderState({
      ...state,
      status: 'error',
      error: 'Add an Aragora API key before refreshing a debate result.',
    });
    return;
  }

  try {
    const debate = await fetchDebate(settings.apiUrl, settings.apiKey, state.debateId);
    const nextState = buildResultState(state, debate);
    await chrome.storage.local.set({ [STATE_KEY]: nextState });
    renderState(nextState);

    if (isTerminalState(nextState)) {
      stopPolling();
    }
  } catch (error) {
    const nextState = {
      ...state,
      status: 'error',
      error: error instanceof Error ? error.message : String(error),
      updatedAt: new Date().toISOString(),
    };
    await chrome.storage.local.set({ [STATE_KEY]: nextState });
    renderState(nextState);
    stopPolling();
  }
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPolling() {
  if (pollTimer) {
    return;
  }

  pollTimer = window.setInterval(() => {
    void refreshDebateState();
  }, 2500);
}

function maybePoll(state) {
  if (state?.debateId && !isTerminalState(state)) {
    startPolling();
    return;
  }

  stopPolling();
}

function cacheElements() {
  elements.statusPill = document.getElementById('status-pill');
  elements.selectionPreview = document.getElementById('selection-preview');
  elements.sourceLink = document.getElementById('source-link');
  elements.apiUrl = document.getElementById('api-url');
  elements.apiKey = document.getElementById('api-key');
  elements.agents = document.getElementById('agents');
  elements.rounds = document.getElementById('rounds');
  elements.saveSettings = document.getElementById('save-settings');
  elements.refreshResult = document.getElementById('refresh-result');
  elements.settingsStatus = document.getElementById('settings-status');
  elements.debateId = document.getElementById('debate-id');
  elements.resultStatus = document.getElementById('result-status');
  elements.resultConfidence = document.getElementById('result-confidence');
  elements.resultAnswer = document.getElementById('result-answer');
  elements.resultError = document.getElementById('result-error');
}

async function initializePopup() {
  cacheElements();

  const [settings, state] = await Promise.all([
    chrome.storage.sync.get(DEFAULT_SETTINGS),
    getStoredState(),
  ]);

  populateSettings(settings);
  renderState(state);
  maybePoll(state);

  elements.saveSettings.addEventListener('click', () => {
    void saveSettings();
  });
  elements.refreshResult.addEventListener('click', () => {
    void refreshDebateState();
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === 'local' && changes[STATE_KEY]) {
      const nextState = changes[STATE_KEY].newValue || null;
      renderState(nextState);
      maybePoll(nextState);
      return;
    }

    if (
      areaName === 'sync' &&
      (changes.apiUrl || changes.apiKey || changes.agents || changes.rounds)
    ) {
      void chrome.storage.sync.get(DEFAULT_SETTINGS).then(populateSettings);
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  void initializePopup();
});
