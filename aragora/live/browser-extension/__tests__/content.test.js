const { createChromeMock, loadExtensionScript } = require('../test-utils');

describe('browser-extension/content.js', () => {
  test('returns the current selection and page metadata to the background script', () => {
    const chrome = createChromeMock();
    document.title = 'Example article';
    window.history.replaceState({}, '', '/doc');
    window.getSelection = jest.fn(() => ({
      toString: () => '  Highlighted claim from the page.  ',
    }));

    loadExtensionScript('content.js', { chrome });
    const sendResponse = jest.fn();

    const handled = chrome.__listeners.messages[0](
      { type: 'aragora:get-selection' },
      {},
      sendResponse,
    );

    expect(handled).toBe(false);
    expect(sendResponse).toHaveBeenCalledWith(
      expect.objectContaining({
        pageTitle: 'Example article',
        selectedText: 'Highlighted claim from the page.',
      }),
    );
    expect(sendResponse.mock.calls[0][0].pageUrl).toContain('/doc');
  });
});
