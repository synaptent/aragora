/**
 * Tests for Zustand stores
 */

import { act } from 'react';

// Reset stores between tests
beforeEach(() => {
  jest.resetModules();
});

describe('debateStore', () => {
  it('should initialize with default state', async () => {
    const { useDebateStore } = await import('../src/store/debateStore');
    const state = useDebateStore.getState();

    expect(state.current.connectionStatus).toBe('idle');
    expect(state.current.messages).toEqual([]);
    expect(state.current.debateId).toBeNull();
    expect(state.artifact).toBeNull();
  });

  it('should add messages with deduplication', async () => {
    const { useDebateStore } = await import('../src/store/debateStore');
    const store = useDebateStore.getState();

    const message = { agent: 'test-agent', content: 'Hello world', timestamp: 1234567890 };

    // First add should succeed
    const added1 = store.addMessage(message);
    expect(added1).toBe(true);
    expect(useDebateStore.getState().current.messages).toHaveLength(1);

    // Duplicate add should be rejected
    const added2 = store.addMessage(message);
    expect(added2).toBe(false);
    expect(useDebateStore.getState().current.messages).toHaveLength(1);
  });

  it('should manage streaming messages', async () => {
    const { useDebateStore } = await import('../src/store/debateStore');
    const store = useDebateStore.getState();

    // Start stream
    act(() => {
      store.startStream('agent1');
    });

    let state = useDebateStore.getState();
    expect(state.current.streamingMessages.has('agent1')).toBe(true);
    expect(state.current.streamingMessages.get('agent1')?.content).toBe('');

    // Append tokens
    act(() => {
      store.appendStreamToken('agent1', 'Hello');
      store.appendStreamToken('agent1', ' world');
    });

    state = useDebateStore.getState();
    expect(state.current.streamingMessages.get('agent1')?.content).toBe('Hello world');

    // End stream - should create a message
    act(() => {
      store.endStream('agent1');
    });

    state = useDebateStore.getState();
    expect(state.current.streamingMessages.has('agent1')).toBe(false);
    expect(state.current.messages).toHaveLength(1);
    expect(state.current.messages[0].content).toBe('Hello world');
  });

  it('should manage connection status', async () => {
    const { useDebateStore } = await import('../src/store/debateStore');
    const store = useDebateStore.getState();

    act(() => {
      store.setConnectionStatus('connecting');
    });
    expect(useDebateStore.getState().current.connectionStatus).toBe('connecting');

    act(() => {
      store.setConnectionStatus('streaming');
    });
    expect(useDebateStore.getState().current.connectionStatus).toBe('streaming');
  });

  it('should reset current state', async () => {
    const { useDebateStore } = await import('../src/store/debateStore');
    const store = useDebateStore.getState();

    // Add some state
    act(() => {
      store.setDebateId('test-123');
      store.addMessage({ agent: 'test', content: 'hello', timestamp: 123 });
      store.setConnectionStatus('streaming');
    });

    // Reset
    act(() => {
      store.resetCurrent();
    });

    const state = useDebateStore.getState();
    expect(state.current.debateId).toBeNull();
    expect(state.current.messages).toEqual([]);
    expect(state.current.connectionStatus).toBe('idle');
  });
});

describe('settingsStore', () => {
  it('should initialize with default preferences', async () => {
    const { useSettingsStore } = await import('../src/store/settingsStore');
    const state = useSettingsStore.getState();

    expect(state.preferences.theme).toBe('dark');
    expect(state.featureConfig.streaming).toBe(true);
    expect(state.apiKeys).toEqual([]);
  });

  it('should update theme', async () => {
    const { useSettingsStore } = await import('../src/store/settingsStore');
    const store = useSettingsStore.getState();

    act(() => {
      store.setTheme('light');
    });

    expect(useSettingsStore.getState().preferences.theme).toBe('light');
  });

  it('should toggle features', async () => {
    const { useSettingsStore } = await import('../src/store/settingsStore');
    const store = useSettingsStore.getState();

    const initial = store.featureConfig.calibration;

    act(() => {
      store.toggleFeature('calibration');
    });

    expect(useSettingsStore.getState().featureConfig.calibration).toBe(!initial);
  });

  it('should manage API keys', async () => {
    const { useSettingsStore } = await import('../src/store/settingsStore');
    const store = useSettingsStore.getState();

    const key = {
      id: 'key-1',
      name: 'Test Key',
      prefix: 'ara_test',
      createdAt: new Date().toISOString(),
    };

    act(() => {
      store.addApiKey(key);
    });

    expect(useSettingsStore.getState().apiKeys).toHaveLength(1);
    expect(useSettingsStore.getState().apiKeys[0].name).toBe('Test Key');

    act(() => {
      store.removeApiKey('key-1');
    });

    expect(useSettingsStore.getState().apiKeys).toHaveLength(0);
  });
});

describe('uiStore', () => {
  it('should initialize with default panel visibility', async () => {
    const { useUIStore } = await import('../src/store/uiStore');
    const state = useUIStore.getState();

    expect(state.panels.sidebar).toBe(true);
    expect(state.panels.agentPanel).toBe(true);
    expect(state.panels.eventsPanel).toBe(false);
  });

  it('should toggle panels', async () => {
    const { useUIStore } = await import('../src/store/uiStore');
    const store = useUIStore.getState();

    act(() => {
      store.togglePanel('eventsPanel');
    });

    expect(useUIStore.getState().panels.eventsPanel).toBe(true);

    act(() => {
      store.togglePanel('eventsPanel');
    });

    expect(useUIStore.getState().panels.eventsPanel).toBe(false);
  });

  it('should manage toasts', async () => {
    const { useUIStore } = await import('../src/store/uiStore');
    const store = useUIStore.getState();

    let toastId: string;

    act(() => {
      toastId = store.addToast({
        type: 'success',
        message: 'Test toast',
        duration: 0, // Don't auto-remove
      });
    });

    expect(useUIStore.getState().toasts).toHaveLength(1);
    expect(useUIStore.getState().toasts[0].message).toBe('Test toast');

    act(() => {
      store.removeToast(toastId);
    });

    expect(useUIStore.getState().toasts).toHaveLength(0);
  });

  it('should manage modal state', async () => {
    const { useUIStore } = await import('../src/store/uiStore');
    const store = useUIStore.getState();

    act(() => {
      store.openModal('export', { debateId: '123' });
    });

    let state = useUIStore.getState();
    expect(state.activeModal).toBe('export');
    expect(state.modalData).toEqual({ debateId: '123' });
    expect(state.focusTrapActive).toBe(true);

    act(() => {
      store.closeModal();
    });

    state = useUIStore.getState();
    expect(state.activeModal).toBeNull();
    expect(state.focusTrapActive).toBe(false);
  });

  it('should set view mode', async () => {
    const { useUIStore } = await import('../src/store/uiStore');
    const store = useUIStore.getState();

    act(() => {
      store.setViewMode('compact');
    });

    expect(useUIStore.getState().viewMode).toBe('compact');
  });
});
