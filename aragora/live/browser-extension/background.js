const MENU_ID = 'aragora-send-selection';
const STATE_KEY = 'aragoraPopupState';
const DEFAULT_SETTINGS = {
  apiUrl: 'https://api.aragora.ai',
  apiKey: '',
  agents: '',
  rounds: 3,
  consensus: 'majority',
};
const ADVERSARIAL_REVIEW_PROMPT =
  'Provide an adversarial review of the selected webpage text. Surface the strongest objections, hidden assumptions, factual uncertainties, risks, and follow-up questions.';
const QUESTION_LIMIT = 5000;
const SELECTION_LIMIT = 9000;

function registerContextMenu() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create(
      { id: MENU_ID, title: 'Send selection to Aragora', contexts: ['selection'] },
      () => {
        if (chrome.runtime.lastError) {
          console.warn(
            'Failed to register Aragora context menu:',
            chrome.runtime.lastError.message,
          );
        }
      },
    );
  });
}

async function ensureDefaultSettings() {
  const settings = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  await chrome.storage.sync.set({ ...DEFAULT_SETTINGS, ...settings });
}

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

function sanitizeSelectionText(value) {
  return String(value || '')
    .replace(/\u0000/g, '')
    .trim()
    .slice(0, SELECTION_LIMIT);
}

function resolveDebateAnswer(result) {
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

function resolveDebateConfidence(result) {
  const rawConfidence =
    result?.confidence ?? result?.consensus?.confidence ?? result?.consensus?.agreement;
  const confidence = typeof rawConfidence === 'string' ? Number(rawConfidence) : rawConfidence;

  return typeof confidence === 'number' && !Number.isNaN(confidence) ? confidence : null;
}

function buildStoredResult(result) {
  const finalAnswer = resolveDebateAnswer(result);

  return {
    debateId: result?.debate_id || result?.id || null,
    status: result?.status || 'running',
    message: result?.message || finalAnswer || null,
    finalAnswer: finalAnswer || null,
    confidence: resolveDebateConfidence(result),
    consensus: result?.consensus || null,
    task: result?.task || result?.environment?.task || '',
  };
}

async function setBadge(text, color) {
  await chrome.action.setBadgeText({ text });

  if (color) {
    await chrome.action.setBadgeBackgroundColor({ color });
  }
}

async function writePopupState(nextState) {
  const current = await chrome.storage.local.get(STATE_KEY);
  const mergedState = {
    ...(current[STATE_KEY] || {}),
    ...nextState,
    updatedAt: new Date().toISOString(),
  };

  await chrome.storage.local.set({ [STATE_KEY]: mergedState });
  return mergedState;
}

async function getSelectionFromContentScript(tabId) {
  if (typeof tabId !== 'number') {
    return null;
  }

  try {
    return await chrome.tabs.sendMessage(tabId, { type: 'aragora:get-selection' });
  } catch (error) {
    console.warn('Could not read selection from content script:', error);
    return null;
  }
}

async function getSettings() {
  return chrome.storage.sync.get(DEFAULT_SETTINGS);
}

function buildRequestPayload(selectionText, source, settings) {
  const titleLine = source.pageTitle ? `Source title: ${source.pageTitle}` : '';
  const urlLine = source.pageUrl ? `Source URL: ${source.pageUrl}` : '';
  const sourceContext = [titleLine, urlLine].filter(Boolean).join('\n');
  const selectionContext =
    selectionText.length > QUESTION_LIMIT
      ? `${selectionText.slice(0, QUESTION_LIMIT)}\n\n[truncated]`
      : selectionText;
  const context = [sourceContext, 'Selected text:', selectionContext].filter(Boolean).join('\n\n');

  const payload = {
    question: ADVERSARIAL_REVIEW_PROMPT,
    rounds: Number(settings.rounds) || DEFAULT_SETTINGS.rounds,
    consensus: settings.consensus || DEFAULT_SETTINGS.consensus,
    auto_select: !String(settings.agents || '').trim(),
    metadata: {
      source: 'browser_extension_context_menu',
      review_type: 'adversarial_selection',
      source_title: source.pageTitle || '',
      source_url: source.pageUrl || '',
    },
  };

  if (context) {
    payload.context = context.slice(0, 10000);
  }

  const agents = String(settings.agents || '').trim();
  if (agents) {
    payload.agents = agents;
  }

  return payload;
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

async function createDebate(selectionText, source, settings) {
  const apiUrl = normalizeApiUrl(settings.apiUrl);
  const response = await fetch(`${apiUrl}/api/v2/debates`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: buildAuthorizationHeader(settings.apiKey),
    },
    body: JSON.stringify(buildRequestPayload(selectionText, source, settings)),
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return response.json();
}

async function handleContextMenuClick(info, tab) {
  let selectionText = sanitizeSelectionText(info.selectionText);
  const source = { pageTitle: tab?.title || '', pageUrl: info.pageUrl || tab?.url || '' };

  if (!selectionText) {
    const contentSelection = await getSelectionFromContentScript(tab?.id);
    selectionText = sanitizeSelectionText(contentSelection?.selectedText);

    if (contentSelection?.pageTitle && !source.pageTitle) {
      source.pageTitle = contentSelection.pageTitle;
    }

    if (contentSelection?.pageUrl && !source.pageUrl) {
      source.pageUrl = contentSelection.pageUrl;
    }
  }

  if (!selectionText) {
    await writePopupState({
      status: 'error',
      error: 'No selected text was available to send.',
      debateId: null,
      result: null,
      selectionText: '',
      source,
    });
    await setBadge('ERR', '#b42318');
    return;
  }

  const settings = await getSettings();
  if (!String(settings.apiKey || '').trim()) {
    await writePopupState({
      status: 'error',
      error: 'Add an Aragora API key in the popup before sending text.',
      debateId: null,
      result: null,
      selectionText,
      source,
    });
    await setBadge('ERR', '#b42318');
    return;
  }

  await writePopupState({
    status: 'submitting',
    error: null,
    debateId: null,
    result: null,
    selectionText,
    source,
    submittedAt: new Date().toISOString(),
  });
  await setBadge('...', '#0f766e');

  try {
    const createdDebate = await createDebate(selectionText, source, settings);
    const debateId = createdDebate.debate_id || createdDebate.id || null;

    if (!debateId) {
      throw new Error('Aragora did not return a debate ID.');
    }

    await writePopupState({
      status: createdDebate.status || 'running',
      debateId,
      error: null,
      result: buildStoredResult(createdDebate),
      selectionText,
      source,
    });
    await setBadge('RUN', '#1d4ed8');
  } catch (error) {
    await writePopupState({
      status: 'error',
      debateId: null,
      result: null,
      error: error instanceof Error ? error.message : String(error),
      selectionText,
      source,
    });
    await setBadge('ERR', '#b42318');
  }
}

chrome.runtime.onInstalled.addListener(() => {
  registerContextMenu();
  void ensureDefaultSettings();
  void setBadge('', null);
});

chrome.runtime.onStartup.addListener(() => {
  registerContextMenu();
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID) {
    return;
  }

  void handleContextMenuClick(info, tab);
});
