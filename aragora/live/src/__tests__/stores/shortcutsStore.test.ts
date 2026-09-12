/**
 * Tests for shortcutsStore
 *
 * Tests cover:
 * - Initial state
 * - Enable/disable shortcuts
 * - Help modal open/close
 * - Custom bindings
 * - Disabled shortcuts
 * - Sequence tracking
 * - Context switching
 * - Reset to defaults
 * - Selectors
 */

import { act, renderHook } from '@testing-library/react';
import {
  useShortcutsStore,
  selectShortcutsEnabled,
  selectHelpOpen,
  selectPendingSequence,
  selectCurrentContext,
  selectIsShortcutDisabled,
  selectCustomBinding,
} from '../../store/shortcutsStore';

describe('shortcutsStore', () => {
  beforeEach(() => {
    // Reset store before each test
    const { result } = renderHook(() => useShortcutsStore());
    act(() => {
      result.current.resetToDefaults();
      result.current.closeHelp();
      result.current.clearSequence();
      result.current.setContext('global');
    });
  });

  describe('Initial State', () => {
    it('has correct initial values', () => {
      const { result } = renderHook(() => useShortcutsStore());

      expect(result.current.enabled).toBe(true);
      expect(result.current.customBindings).toEqual({});
      expect(result.current.disabledShortcuts).toEqual([]);
      expect(result.current.isHelpOpen).toBe(false);
      expect(result.current.pendingSequence).toEqual([]);
      expect(result.current.sequenceStartTime).toBeNull();
      expect(result.current.currentContext).toBe('global');
    });
  });

  describe('Enable/Disable Actions', () => {
    it('setEnabled updates enabled state', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.setEnabled(false);
      });
      expect(result.current.enabled).toBe(false);

      act(() => {
        result.current.setEnabled(true);
      });
      expect(result.current.enabled).toBe(true);
    });

    it('toggleEnabled toggles enabled state', () => {
      const { result } = renderHook(() => useShortcutsStore());

      expect(result.current.enabled).toBe(true);

      act(() => {
        result.current.toggleEnabled();
      });
      expect(result.current.enabled).toBe(false);

      act(() => {
        result.current.toggleEnabled();
      });
      expect(result.current.enabled).toBe(true);
    });
  });

  describe('Help Modal Actions', () => {
    it('openHelp opens help modal', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.openHelp();
      });
      expect(result.current.isHelpOpen).toBe(true);
    });

    it('closeHelp closes help modal', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.openHelp();
      });

      act(() => {
        result.current.closeHelp();
      });
      expect(result.current.isHelpOpen).toBe(false);
    });

    it('toggleHelp toggles help modal', () => {
      const { result } = renderHook(() => useShortcutsStore());

      expect(result.current.isHelpOpen).toBe(false);

      act(() => {
        result.current.toggleHelp();
      });
      expect(result.current.isHelpOpen).toBe(true);

      act(() => {
        result.current.toggleHelp();
      });
      expect(result.current.isHelpOpen).toBe(false);
    });
  });

  describe('Custom Bindings Actions', () => {
    it('setCustomBinding sets custom key binding', () => {
      const { result } = renderHook(() => useShortcutsStore());

      const customBinding = [{ key: 'h', modifiers: ['ctrl' as const] }];

      act(() => {
        result.current.setCustomBinding('nav-hub', customBinding);
      });

      expect(result.current.customBindings['nav-hub']).toEqual(customBinding);
    });

    it('setCustomBinding can set multiple bindings', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.setCustomBinding('shortcut1', [{ key: 'a' }]);
        result.current.setCustomBinding('shortcut2', [{ key: 'b' }]);
      });

      expect(Object.keys(result.current.customBindings)).toHaveLength(2);
      expect(result.current.customBindings['shortcut1']).toEqual([{ key: 'a' }]);
      expect(result.current.customBindings['shortcut2']).toEqual([{ key: 'b' }]);
    });

    it('clearCustomBinding removes custom binding', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.setCustomBinding('nav-hub', [{ key: 'h' }]);
        result.current.setCustomBinding('nav-debates', [{ key: 'd' }]);
      });

      expect(Object.keys(result.current.customBindings)).toHaveLength(2);

      act(() => {
        result.current.clearCustomBinding('nav-hub');
      });

      expect(result.current.customBindings['nav-hub']).toBeUndefined();
      expect(result.current.customBindings['nav-debates']).toEqual([{ key: 'd' }]);
    });
  });

  describe('Disabled Shortcuts Actions', () => {
    it('disableShortcut adds shortcut to disabled list', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.disableShortcut('nav-hub');
      });

      expect(result.current.disabledShortcuts).toContain('nav-hub');
    });

    it('disableShortcut does not add duplicates', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.disableShortcut('nav-hub');
        result.current.disableShortcut('nav-hub');
      });

      expect(result.current.disabledShortcuts.filter((id) => id === 'nav-hub')).toHaveLength(1);
    });

    it('enableShortcut removes shortcut from disabled list', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.disableShortcut('nav-hub');
        result.current.disableShortcut('nav-debates');
      });

      expect(result.current.disabledShortcuts).toHaveLength(2);

      act(() => {
        result.current.enableShortcut('nav-hub');
      });

      expect(result.current.disabledShortcuts).not.toContain('nav-hub');
      expect(result.current.disabledShortcuts).toContain('nav-debates');
    });

    it('enableShortcut handles non-existent shortcut gracefully', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.enableShortcut('non-existent');
      });

      expect(result.current.disabledShortcuts).toEqual([]);
    });
  });

  describe('Sequence Tracking Actions', () => {
    it('addToSequence adds key to pending sequence', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.addToSequence('g');
      });

      expect(result.current.pendingSequence).toEqual(['g']);
      expect(result.current.sequenceStartTime).not.toBeNull();
    });

    it('addToSequence builds multi-key sequence', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.addToSequence('g');
        result.current.addToSequence('i');
      });

      expect(result.current.pendingSequence).toEqual(['g', 'i']);
    });

    it('addToSequence preserves start time on subsequent adds', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.addToSequence('g');
      });

      const startTime = result.current.sequenceStartTime;

      act(() => {
        result.current.addToSequence('i');
      });

      expect(result.current.sequenceStartTime).toBe(startTime);
    });

    it('clearSequence resets sequence state', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.addToSequence('g');
        result.current.addToSequence('i');
      });

      expect(result.current.pendingSequence).toHaveLength(2);
      expect(result.current.sequenceStartTime).not.toBeNull();

      act(() => {
        result.current.clearSequence();
      });

      expect(result.current.pendingSequence).toEqual([]);
      expect(result.current.sequenceStartTime).toBeNull();
    });
  });

  describe('Context Actions', () => {
    it('setContext updates current context', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.setContext('debate');
      });
      expect(result.current.currentContext).toBe('debate');

      act(() => {
        result.current.setContext('list');
      });
      expect(result.current.currentContext).toBe('list');

      act(() => {
        result.current.setContext('editor');
      });
      expect(result.current.currentContext).toBe('editor');

      act(() => {
        result.current.setContext('global');
      });
      expect(result.current.currentContext).toBe('global');
    });
  });

  describe('Reset Actions', () => {
    it('resetToDefaults resets preferences to defaults', () => {
      const { result } = renderHook(() => useShortcutsStore());

      // Modify state
      act(() => {
        result.current.setEnabled(false);
        result.current.setCustomBinding('nav-hub', [{ key: 'h' }]);
        result.current.disableShortcut('nav-debates');
      });

      // Verify modifications
      expect(result.current.enabled).toBe(false);
      expect(result.current.customBindings['nav-hub']).toBeDefined();
      expect(result.current.disabledShortcuts).toContain('nav-debates');

      // Reset
      act(() => {
        result.current.resetToDefaults();
      });

      // Verify reset
      expect(result.current.enabled).toBe(true);
      expect(result.current.customBindings).toEqual({});
      expect(result.current.disabledShortcuts).toEqual([]);
    });
  });

  describe('Selectors', () => {
    it('selectShortcutsEnabled returns enabled state', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.setEnabled(false);
      });

      expect(selectShortcutsEnabled(result.current)).toBe(false);
    });

    it('selectHelpOpen returns help modal state', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.openHelp();
      });

      expect(selectHelpOpen(result.current)).toBe(true);
    });

    it('selectPendingSequence returns pending sequence', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.addToSequence('g');
        result.current.addToSequence('i');
      });

      expect(selectPendingSequence(result.current)).toEqual(['g', 'i']);
    });

    it('selectCurrentContext returns current context', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.setContext('debate');
      });

      expect(selectCurrentContext(result.current)).toBe('debate');
    });

    it('selectIsShortcutDisabled checks if shortcut is disabled', () => {
      const { result } = renderHook(() => useShortcutsStore());

      act(() => {
        result.current.disableShortcut('nav-hub');
      });

      expect(selectIsShortcutDisabled(result.current, 'nav-hub')).toBe(true);
      expect(selectIsShortcutDisabled(result.current, 'nav-debates')).toBe(false);
    });

    it('selectCustomBinding returns custom binding', () => {
      const { result } = renderHook(() => useShortcutsStore());

      const binding = [{ key: 'h', modifiers: ['ctrl' as const] }];

      act(() => {
        result.current.setCustomBinding('nav-hub', binding);
      });

      expect(selectCustomBinding(result.current, 'nav-hub')).toEqual(binding);
      expect(selectCustomBinding(result.current, 'non-existent')).toBeUndefined();
    });
  });
});
