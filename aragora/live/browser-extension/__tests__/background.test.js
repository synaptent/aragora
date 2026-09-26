const { createChromeMock, flushMicrotasks, loadExtensionScript } = require('../test-utils');

describe('browser-extension/background.js', () => {
  test('submits selected text with normalized auth and stores running debate state', async () => {
    const chrome = createChromeMock({
      syncState: {
        agents: 'claude,gemini',
        apiKey: 'token-123',
        apiUrl: 'https://api.example.com/',
        rounds: 4,
      },
    });
    const fetchMock = jest
      .fn()
      .mockResolvedValue({
        json: async () => ({ debate_id: 'debate-123', message: 'Queued', status: 'running' }),
        ok: true,
      });

    const { context } = loadExtensionScript('background.js', { chrome, fetchMock });

    await context.handleContextMenuClick(
      {
        pageUrl: 'https://example.com/source',
        selectionText: '  Important claim with hidden assumption.  ',
      },
      { id: 9, title: 'Example source', url: 'https://example.com/source' },
    );
    await flushMicrotasks();

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/api/v2/debates',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer token-123',
          'Content-Type': 'application/json',
        }),
        method: 'POST',
      }),
    );

    const payload = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(payload).toMatchObject({
      agents: 'claude,gemini',
      auto_select: false,
      consensus: 'majority',
      metadata: {
        review_type: 'adversarial_selection',
        source: 'browser_extension_context_menu',
        source_title: 'Example source',
        source_url: 'https://example.com/source',
      },
      question: expect.stringContaining('adversarial review'),
      rounds: 4,
    });
    expect(payload.context).toContain('Selected text:');
    expect(payload.context).toContain('Important claim with hidden assumption.');

    expect(chrome.storage.local.__getState().aragoraPopupState).toMatchObject({
      debateId: 'debate-123',
      result: { message: 'Queued', status: 'running' },
      selectionText: 'Important claim with hidden assumption.',
      source: { pageTitle: 'Example source', pageUrl: 'https://example.com/source' },
      status: 'running',
    });
    expect(chrome.action.setBadgeText).toHaveBeenLastCalledWith({ text: 'RUN' });
  });

  test('preserves an already-prefixed bearer token', async () => {
    const chrome = createChromeMock({ syncState: { apiKey: 'Bearer token-123' } });
    const fetchMock = jest
      .fn()
      .mockResolvedValue({
        json: async () => ({ debate_id: 'debate-456', status: 'running' }),
        ok: true,
      });

    const { context } = loadExtensionScript('background.js', { chrome, fetchMock });

    await context.handleContextMenuClick({ selectionText: 'Claim' }, { id: 3, title: 'Example' });
    await flushMicrotasks();

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer token-123');
  });

  test('stores a popup error and skips the network call when no API key is configured', async () => {
    const chrome = createChromeMock({ syncState: { apiKey: '' } });
    const fetchMock = jest.fn();

    const { context } = loadExtensionScript('background.js', { chrome, fetchMock });

    await context.handleContextMenuClick(
      { pageUrl: 'https://example.com/source', selectionText: 'Claim' },
      { id: 2, title: 'Example source' },
    );
    await flushMicrotasks();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(chrome.storage.local.__getState().aragoraPopupState).toMatchObject({
      debateId: null,
      error: 'Add an Aragora API key in the popup before sending text.',
      status: 'error',
    });
    expect(chrome.action.setBadgeText).toHaveBeenLastCalledWith({ text: 'ERR' });
  });
});
