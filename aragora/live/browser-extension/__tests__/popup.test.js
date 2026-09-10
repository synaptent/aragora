const {
  createChromeMock,
  flushMicrotasks,
  loadExtensionScript,
  loadPopupDocument,
} = require('../test-utils');

describe('browser-extension/popup.js', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    loadPopupDocument();
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  test('renders stored state and refreshes a completed debate with normalized auth', async () => {
    const chrome = createChromeMock({
      localState: {
        aragoraPopupState: {
          debateId: 'debate-123',
          result: { status: 'running' },
          selectionText: 'Selected snippet',
          source: { pageTitle: 'Example page', pageUrl: 'https://example.com/page' },
          status: 'running',
        },
      },
      syncState: { apiKey: 'token-123', apiUrl: 'https://api.example.com/' },
    });
    const fetchMock = jest
      .fn()
      .mockResolvedValue({
        json: async () => ({
          consensus: { confidence: 0.82, summary: 'Aragora found the claim under-evidenced.' },
          id: 'debate-123',
          status: 'completed',
        }),
        ok: true,
      });

    const { context } = loadExtensionScript('popup.js', { chrome, fetchMock });
    await context.initializePopup();
    await flushMicrotasks();

    expect(document.getElementById('selection-preview').textContent).toContain('Selected snippet');
    expect(document.getElementById('source-link').textContent).toBe('Example page');

    await context.refreshDebateState();
    await flushMicrotasks();

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/api/v2/debates/debate-123',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer token-123',
          'Content-Type': 'application/json',
        }),
      }),
    );
    expect(document.getElementById('status-pill').textContent).toBe('Completed');
    expect(document.getElementById('result-status').textContent).toBe('Completed');
    expect(document.getElementById('result-confidence').textContent).toBe('82%');
    expect(document.getElementById('result-answer').textContent).toBe(
      'Aragora found the claim under-evidenced.',
    );
    expect(chrome.storage.local.__getState().aragoraPopupState).toMatchObject({
      debateId: 'debate-123',
      result: {
        confidence: 0.82,
        finalAnswer: 'Aragora found the claim under-evidenced.',
        status: 'completed',
      },
      status: 'completed',
    });
  });

  test('saves settings with bounded rounds and preserves bearer-prefixed tokens', async () => {
    const chrome = createChromeMock({
      syncState: { apiKey: 'Bearer preset-token', apiUrl: 'https://api.example.com', rounds: 3 },
    });
    const fetchMock = jest.fn();

    const { context } = loadExtensionScript('popup.js', { chrome, fetchMock });
    await context.initializePopup();
    await flushMicrotasks();

    document.getElementById('api-url').value = 'https://api.example.com/';
    document.getElementById('api-key').value = 'Bearer preset-token';
    document.getElementById('rounds').value = '99';
    await context.saveSettings();
    await flushMicrotasks();

    expect(chrome.storage.sync.__getState()).toMatchObject({
      apiKey: 'Bearer preset-token',
      apiUrl: 'https://api.example.com/',
      rounds: 20,
    });
    expect(document.getElementById('settings-status').textContent).toBe('Saved');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
