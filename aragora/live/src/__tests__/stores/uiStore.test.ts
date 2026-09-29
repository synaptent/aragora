/**
 * Tests for uiStore
 *
 * Tests cover:
 * - Initial state
 * - View mode actions
 * - Panel visibility actions
 * - Panel position actions
 * - Modal actions
 * - Toast actions
 * - Loading state actions
 * - Keyboard shortcuts toggle
 * - Focus trap toggle
 * - Reset actions
 * - Selectors
 */

import { act, renderHook } from '@testing-library/react';
import {
  useUIStore,
  selectViewMode,
  selectMobileViewMode,
  selectIsMobile,
  selectPanels,
  selectPanelPositions,
  selectActiveModal,
  selectModalData,
  selectToasts,
  selectGlobalLoading,
  selectKeyboardShortcutsEnabled,
} from '../../store/uiStore';

describe('uiStore', () => {
  beforeEach(() => {
    // Reset store before each test
    const { result } = renderHook(() => useUIStore());
    act(() => {
      result.current.resetAll();
    });
  });

  describe('Initial State', () => {
    it('has correct initial values', () => {
      const { result } = renderHook(() => useUIStore());

      expect(result.current.viewMode).toBe('default');
      expect(result.current.mobileViewMode).toBe('transcript');
      expect(result.current.isMobile).toBe(false);
      expect(result.current.activeModal).toBeNull();
      expect(result.current.toasts).toEqual([]);
      expect(result.current.globalLoading).toBe(false);
      expect(result.current.keyboardShortcutsEnabled).toBe(true);
      expect(result.current.focusTrapActive).toBe(false);
    });

    it('has correct default panel visibility', () => {
      const { result } = renderHook(() => useUIStore());

      expect(result.current.panels.sidebar).toBe(true);
      expect(result.current.panels.agentPanel).toBe(true);
      expect(result.current.panels.eventsPanel).toBe(false);
      expect(result.current.panels.participationPanel).toBe(false);
      expect(result.current.panels.citationsPanel).toBe(false);
      expect(result.current.panels.analyticsPanel).toBe(false);
      expect(result.current.panels.historyPanel).toBe(false);
    });
  });

  describe('View Mode Actions', () => {
    it('setViewMode updates view mode', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setViewMode('compact');
      });
      expect(result.current.viewMode).toBe('compact');

      act(() => {
        result.current.setViewMode('expanded');
      });
      expect(result.current.viewMode).toBe('expanded');
    });

    it('setMobileViewMode updates mobile view mode', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setMobileViewMode('agents');
      });
      expect(result.current.mobileViewMode).toBe('agents');

      act(() => {
        result.current.setMobileViewMode('events');
      });
      expect(result.current.mobileViewMode).toBe('events');
    });

    it('setIsMobile updates mobile state', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setIsMobile(true);
      });
      expect(result.current.isMobile).toBe(true);

      act(() => {
        result.current.setIsMobile(false);
      });
      expect(result.current.isMobile).toBe(false);
    });
  });

  describe('Panel Visibility Actions', () => {
    it('togglePanel toggles panel visibility', () => {
      const { result } = renderHook(() => useUIStore());

      // Sidebar is true by default
      expect(result.current.panels.sidebar).toBe(true);

      act(() => {
        result.current.togglePanel('sidebar');
      });
      expect(result.current.panels.sidebar).toBe(false);

      act(() => {
        result.current.togglePanel('sidebar');
      });
      expect(result.current.panels.sidebar).toBe(true);
    });

    it('setPanel sets specific panel visibility', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setPanel('eventsPanel', true);
      });
      expect(result.current.panels.eventsPanel).toBe(true);

      act(() => {
        result.current.setPanel('eventsPanel', false);
      });
      expect(result.current.panels.eventsPanel).toBe(false);
    });

    it('setPanels updates multiple panels at once', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setPanels({ sidebar: false, eventsPanel: true, analyticsPanel: true });
      });

      expect(result.current.panels.sidebar).toBe(false);
      expect(result.current.panels.eventsPanel).toBe(true);
      expect(result.current.panels.analyticsPanel).toBe(true);
      // Others should remain unchanged
      expect(result.current.panels.agentPanel).toBe(true);
    });

    it('resetPanels restores default panel visibility', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setPanels({ sidebar: false, eventsPanel: true, analyticsPanel: true });
      });

      act(() => {
        result.current.resetPanels();
      });

      expect(result.current.panels.sidebar).toBe(true);
      expect(result.current.panels.eventsPanel).toBe(false);
      expect(result.current.panels.analyticsPanel).toBe(false);
    });
  });

  describe('Panel Position Actions', () => {
    it('setPanelPosition sets panel position', () => {
      const { result } = renderHook(() => useUIStore());

      const position = { x: 100, y: 200, width: 300, height: 400 };

      act(() => {
        result.current.setPanelPosition('testPanel', position);
      });

      expect(result.current.panelPositions['testPanel']).toEqual(position);
    });

    it('resetPanelPositions clears all positions', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setPanelPosition('panel1', { x: 100, y: 100 });
        result.current.setPanelPosition('panel2', { x: 200, y: 200 });
      });

      expect(Object.keys(result.current.panelPositions)).toHaveLength(2);

      act(() => {
        result.current.resetPanelPositions();
      });

      expect(result.current.panelPositions).toEqual({});
    });
  });

  describe('Modal Actions', () => {
    it('openModal sets active modal and data', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.openModal('testModal', { key: 'value' });
      });

      expect(result.current.activeModal).toBe('testModal');
      expect(result.current.modalData).toEqual({ key: 'value' });
      expect(result.current.focusTrapActive).toBe(true);
    });

    it('openModal without data sets empty object', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.openModal('testModal');
      });

      expect(result.current.activeModal).toBe('testModal');
      expect(result.current.modalData).toEqual({});
    });

    it('closeModal clears modal state', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.openModal('testModal', { key: 'value' });
      });

      act(() => {
        result.current.closeModal();
      });

      expect(result.current.activeModal).toBeNull();
      expect(result.current.modalData).toEqual({});
      expect(result.current.focusTrapActive).toBe(false);
    });

    it('setModalData merges modal data', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.openModal('testModal', { key1: 'value1' });
      });

      act(() => {
        result.current.setModalData({ key2: 'value2' });
      });

      expect(result.current.modalData).toEqual({ key1: 'value1', key2: 'value2' });
    });
  });

  describe('Toast Actions', () => {
    it('addToast adds a toast message', () => {
      const { result } = renderHook(() => useUIStore());

      let toastId: string;
      act(() => {
        toastId = result.current.addToast({
          type: 'success',
          message: 'Test message',
          duration: 0, // Prevent auto-removal
        });
      });

      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].type).toBe('success');
      expect(result.current.toasts[0].message).toBe('Test message');
      expect(result.current.toasts[0].id).toBe(toastId!);
    });

    it('addToast generates unique IDs', () => {
      const { result } = renderHook(() => useUIStore());

      let id1: string;
      let id2: string;

      act(() => {
        id1 = result.current.addToast({ type: 'info', message: 'Toast 1', duration: 0 });
        id2 = result.current.addToast({ type: 'info', message: 'Toast 2', duration: 0 });
      });

      expect(id1!).not.toBe(id2!);
    });

    it('removeToast removes specific toast', () => {
      const { result } = renderHook(() => useUIStore());

      let toastId: string;
      act(() => {
        toastId = result.current.addToast({ type: 'info', message: 'Test', duration: 0 });
        result.current.addToast({ type: 'info', message: 'Other', duration: 0 });
      });

      expect(result.current.toasts).toHaveLength(2);

      act(() => {
        result.current.removeToast(toastId!);
      });

      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].message).toBe('Other');
    });

    it('clearToasts removes all toasts', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.addToast({ type: 'info', message: 'Toast 1', duration: 0 });
        result.current.addToast({ type: 'info', message: 'Toast 2', duration: 0 });
        result.current.addToast({ type: 'info', message: 'Toast 3', duration: 0 });
      });

      expect(result.current.toasts).toHaveLength(3);

      act(() => {
        result.current.clearToasts();
      });

      expect(result.current.toasts).toHaveLength(0);
    });
  });

  describe('Loading State Actions', () => {
    it('setGlobalLoading sets loading state with message', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setGlobalLoading(true, 'Loading data...');
      });

      expect(result.current.globalLoading).toBe(true);
      expect(result.current.loadingMessage).toBe('Loading data...');
    });

    it('setGlobalLoading clears message when not provided', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setGlobalLoading(true, 'Loading...');
      });

      act(() => {
        result.current.setGlobalLoading(false);
      });

      expect(result.current.globalLoading).toBe(false);
      expect(result.current.loadingMessage).toBe('');
    });
  });

  describe('Keyboard Shortcuts Toggle', () => {
    it('setKeyboardShortcutsEnabled updates state', () => {
      const { result } = renderHook(() => useUIStore());

      expect(result.current.keyboardShortcutsEnabled).toBe(true);

      act(() => {
        result.current.setKeyboardShortcutsEnabled(false);
      });

      expect(result.current.keyboardShortcutsEnabled).toBe(false);

      act(() => {
        result.current.setKeyboardShortcutsEnabled(true);
      });

      expect(result.current.keyboardShortcutsEnabled).toBe(true);
    });
  });

  describe('Focus Trap Toggle', () => {
    it('setFocusTrapActive updates state', () => {
      const { result } = renderHook(() => useUIStore());

      expect(result.current.focusTrapActive).toBe(false);

      act(() => {
        result.current.setFocusTrapActive(true);
      });

      expect(result.current.focusTrapActive).toBe(true);
    });
  });

  describe('Reset Actions', () => {
    it('resetAll restores all state to defaults', () => {
      const { result } = renderHook(() => useUIStore());

      // Modify various state
      act(() => {
        result.current.setViewMode('compact');
        result.current.setIsMobile(true);
        result.current.setPanels({ sidebar: false, eventsPanel: true });
        result.current.openModal('testModal', { data: 'test' });
        result.current.addToast({ type: 'info', message: 'Test', duration: 0 });
        result.current.setGlobalLoading(true, 'Loading');
        result.current.setKeyboardShortcutsEnabled(false);
      });

      // Verify state was modified
      expect(result.current.viewMode).toBe('compact');
      expect(result.current.isMobile).toBe(true);
      expect(result.current.activeModal).toBe('testModal');
      expect(result.current.toasts.length).toBeGreaterThan(0);

      // Reset
      act(() => {
        result.current.resetAll();
      });

      // Verify all state is reset
      expect(result.current.viewMode).toBe('default');
      expect(result.current.mobileViewMode).toBe('transcript');
      expect(result.current.isMobile).toBe(false);
      expect(result.current.panels.sidebar).toBe(true);
      expect(result.current.panels.eventsPanel).toBe(false);
      expect(result.current.activeModal).toBeNull();
      expect(result.current.toasts).toEqual([]);
      expect(result.current.globalLoading).toBe(false);
      expect(result.current.keyboardShortcutsEnabled).toBe(true);
      expect(result.current.focusTrapActive).toBe(false);
    });
  });

  describe('Selectors', () => {
    it('selectViewMode returns view mode', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setViewMode('expanded');
      });

      expect(selectViewMode(result.current)).toBe('expanded');
    });

    it('selectMobileViewMode returns mobile view mode', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setMobileViewMode('events');
      });

      expect(selectMobileViewMode(result.current)).toBe('events');
    });

    it('selectIsMobile returns mobile state', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setIsMobile(true);
      });

      expect(selectIsMobile(result.current)).toBe(true);
    });

    it('selectPanels returns panel visibility', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setPanel('eventsPanel', true);
      });

      const panels = selectPanels(result.current);
      expect(panels.eventsPanel).toBe(true);
    });

    it('selectPanelPositions returns panel positions', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setPanelPosition('test', { x: 50, y: 100 });
      });

      const positions = selectPanelPositions(result.current);
      expect(positions['test']).toEqual({ x: 50, y: 100 });
    });

    it('selectActiveModal returns active modal', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.openModal('myModal');
      });

      expect(selectActiveModal(result.current)).toBe('myModal');
    });

    it('selectModalData returns modal data', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.openModal('myModal', { key: 'value' });
      });

      expect(selectModalData(result.current)).toEqual({ key: 'value' });
    });

    it('selectToasts returns toasts', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.addToast({ type: 'success', message: 'Test', duration: 0 });
      });

      const toasts = selectToasts(result.current);
      expect(toasts).toHaveLength(1);
      expect(toasts[0].message).toBe('Test');
    });

    it('selectGlobalLoading returns loading state', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setGlobalLoading(true, 'Please wait');
      });

      const loadingState = selectGlobalLoading(result.current);
      expect(loadingState.loading).toBe(true);
      expect(loadingState.message).toBe('Please wait');
    });

    it('selectKeyboardShortcutsEnabled returns shortcuts enabled state', () => {
      const { result } = renderHook(() => useUIStore());

      act(() => {
        result.current.setKeyboardShortcutsEnabled(false);
      });

      expect(selectKeyboardShortcutsEnabled(result.current)).toBe(false);
    });
  });
});
