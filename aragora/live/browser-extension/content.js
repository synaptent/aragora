const MAX_SELECTION_LENGTH = 9000;

function getSelectionText() {
  const selection = window.getSelection();
  if (!selection) {
    return '';
  }

  return String(selection.toString() || '')
    .replace(/\u0000/g, '')
    .trim()
    .slice(0, MAX_SELECTION_LENGTH);
}

function buildSelectionPayload() {
  return {
    selectedText: getSelectionText(),
    pageTitle: document.title || '',
    pageUrl: window.location.href,
  };
}

function captureSelection() {
  window.__aragoraSelection = buildSelectionPayload();
}

['selectionchange', 'mouseup', 'keyup', 'contextmenu'].forEach((eventName) => {
  document.addEventListener(eventName, captureSelection, true);
});

window.addEventListener('focus', captureSelection, true);
captureSelection();

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'aragora:get-selection') {
    return false;
  }

  captureSelection();
  sendResponse(window.__aragoraSelection || buildSelectionPayload());
  return false;
});
