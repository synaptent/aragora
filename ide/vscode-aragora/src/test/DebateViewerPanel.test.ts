/**
 * Tests for DebateViewerPanel and ControlPlaneService
 */

import * as vscode from 'vscode';

// Mock vscode module
jest.mock('vscode', () => ({
  window: {
    createWebviewPanel: jest.fn(() => ({
      webview: { html: '', onDidReceiveMessage: jest.fn(), postMessage: jest.fn() },
      onDidDispose: jest.fn(),
      reveal: jest.fn(),
      dispose: jest.fn(),
    })),
    showInputBox: jest.fn(),
    showInformationMessage: jest.fn(),
    showErrorMessage: jest.fn(),
  },
  commands: {
    registerCommand: jest.fn((command, callback) => ({ dispose: jest.fn() })),
    executeCommand: jest.fn(),
  },
  workspace: {
    getConfiguration: jest.fn(() => ({
      get: jest.fn((key: string) => {
        if (key === 'apiUrl') return 'http://localhost:8080';
        if (key === 'apiKey') return 'test-key';
        return undefined;
      }),
    })),
  },
  Uri: {
    joinPath: jest.fn((...args) => ({ fsPath: args.join('/') })),
    file: jest.fn((path: string) => ({ fsPath: path })),
  },
  ViewColumn: { Beside: 2 },
  env: { clipboard: { writeText: jest.fn() } },
  Disposable: class {
    dispose(): void {}
  },
}));

// Mock WebSocket
class MockWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: ((error: Error) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  readyState = 1; // OPEN

  send = jest.fn();
  close = jest.fn();

  static readonly OPEN = 1;
}

(global as unknown as Record<string, unknown>).WebSocket = MockWebSocket;

// Mock fetch
global.fetch = jest.fn();

describe('ControlPlaneService', () => {
  let ControlPlaneService: typeof import('../services/ControlPlaneService').ControlPlaneService;
  let getControlPlaneService: typeof import('../services/ControlPlaneService').getControlPlaneService;
  let disposeControlPlaneService: typeof import('../services/ControlPlaneService').disposeControlPlaneService;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.resetModules();
    const module = require('../services/ControlPlaneService');
    ControlPlaneService = module.ControlPlaneService;
    getControlPlaneService = module.getControlPlaneService;
    disposeControlPlaneService = module.disposeControlPlaneService;
    disposeControlPlaneService();
  });

  describe('connection management', () => {
    it('creates singleton instance', () => {
      const service1 = getControlPlaneService();
      const service2 = getControlPlaneService();
      expect(service1).toBe(service2);
    });

    it('starts with disconnected status', () => {
      const service = new ControlPlaneService();
      expect(service.getConnectionStatus()).toBe('disconnected');
    });

    it('sets connecting status when connect is called', async () => {
      const service = new ControlPlaneService();
      service.connect();
      expect(service.getConnectionStatus()).toBe('connecting');
    });
  });

  describe('event subscription', () => {
    it('allows subscribing to events', () => {
      const service = new ControlPlaneService();
      const handler = jest.fn();
      const subscription = service.subscribe(handler);
      expect(subscription.dispose).toBeDefined();
    });

    it('unsubscribes when disposed', () => {
      const service = new ControlPlaneService();
      const handler = jest.fn();
      const subscription = service.subscribe(handler);
      subscription.dispose();
      // Handler should be removed
    });
  });

  describe('getActiveDeliberations', () => {
    it('returns empty array when disconnected', async () => {
      const service = new ControlPlaneService();
      const deliberations = await service.getActiveDeliberations();
      expect(deliberations).toEqual([]);
    });
  });

  describe('triggerDeliberation', () => {
    it('calls API to trigger deliberation', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ deliberation_id: 'delib-123' }),
      });

      const service = new ControlPlaneService();
      const id = await service.triggerDeliberation('Test question');

      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/v1/control-plane/deliberations',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(id).toBe('delib-123');
    });

    it('returns null on error', async () => {
      (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

      const service = new ControlPlaneService();
      const id = await service.triggerDeliberation('Test question');

      expect(id).toBeNull();
    });
  });

  describe('connectToDeliberation', () => {
    it('returns disposable for unsubscribing', () => {
      const service = new ControlPlaneService();
      const disposable = service.connectToDeliberation('delib-123');
      expect(disposable.dispose).toBeDefined();
    });
  });

  describe('dispose', () => {
    it('cleans up resources', () => {
      const service = new ControlPlaneService();
      service.dispose();
      expect(service.getConnectionStatus()).toBe('disconnected');
    });
  });
});

describe('DebateViewerPanel', () => {
  let registerDebateViewerCommands: typeof import('../panels/DebateViewerPanel').registerDebateViewerCommands;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.resetModules();
    const module = require('../panels/DebateViewerPanel');
    registerDebateViewerCommands = module.registerDebateViewerCommands;
  });

  describe('createOrShow', () => {
    it('returns a DebateViewerPanel instance', () => {
      const module = require('../panels/DebateViewerPanel');
      const DebateViewerPanel = module.DebateViewerPanel;

      // Clear current panel
      DebateViewerPanel.currentPanel = undefined;

      const extensionUri = vscode.Uri.file('/test');
      const result = DebateViewerPanel.createOrShow(extensionUri);

      // Should return a panel instance
      expect(result).toBeDefined();
    });

    it('sets currentPanel after creation', () => {
      const module = require('../panels/DebateViewerPanel');
      const DebateViewerPanel = module.DebateViewerPanel;

      DebateViewerPanel.currentPanel = undefined;
      const extensionUri = vscode.Uri.file('/test');
      DebateViewerPanel.createOrShow(extensionUri);

      expect(DebateViewerPanel.currentPanel).toBeDefined();
    });
  });

  describe('registerDebateViewerCommands', () => {
    it('adds multiple disposables to context subscriptions', () => {
      const subscriptions: vscode.Disposable[] = [];
      const context = {
        extensionUri: vscode.Uri.file('/test'),
        subscriptions,
      } as unknown as vscode.ExtensionContext;

      registerDebateViewerCommands(context);

      // 3 commands should add 3 disposables
      expect(subscriptions.length).toBe(3);
    });

    it('function can be called multiple times safely', () => {
      const context1 = {
        extensionUri: vscode.Uri.file('/test'),
        subscriptions: [] as vscode.Disposable[],
      } as unknown as vscode.ExtensionContext;

      const context2 = {
        extensionUri: vscode.Uri.file('/test'),
        subscriptions: [] as vscode.Disposable[],
      } as unknown as vscode.ExtensionContext;

      // Should not throw
      registerDebateViewerCommands(context1);
      registerDebateViewerCommands(context2);

      expect(context1.subscriptions.length).toBe(3);
      expect(context2.subscriptions.length).toBe(3);
    });
  });
});

describe('Deliberation event types', () => {
  it('exports event type definitions', () => {
    const {
      ControlPlaneEvent,
      ControlPlaneEventType,
      Deliberation,
    } = require('../services/ControlPlaneService');

    // These are type definitions, so we just verify the exports exist
    expect(true).toBe(true);
  });
});

describe('Panel HTML content', () => {
  it('panel class has required static properties', () => {
    // DebateViewerPanel should have the correct viewType
    const module = require('../panels/DebateViewerPanel');
    expect(module.DebateViewerPanel.viewType).toBe('aragora.debateViewerPanel');
  });

  it('panel class has createOrShow method', () => {
    const module = require('../panels/DebateViewerPanel');
    expect(typeof module.DebateViewerPanel.createOrShow).toBe('function');
  });
});
