'use client';

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type { KeyBinding, ShortcutsPreferences } from '@/lib/shortcuts/types';

// ============================================================================
// Types
// ============================================================================

interface ShortcutsState extends ShortcutsPreferences {
  /**
   * Whether the shortcuts help modal is currently open
   */
  isHelpOpen: boolean;

  /**
   * Current pending key sequence (for multi-key shortcuts like g+i)
   */
  pendingSequence: string[];

  /**
   * Timestamp when the sequence started (for timeout)
   */
  sequenceStartTime: number | null;

  /**
   * Current context for context-aware shortcuts
   */
  currentContext: 'global' | 'debate' | 'list' | 'editor';
}

interface ShortcutsActions {
  /**
   * Toggle shortcuts enabled/disabled
   */
  setEnabled: (enabled: boolean) => void;

  /**
   * Toggle shortcuts enabled state
   */
  toggleEnabled: () => void;

  /**
   * Open the shortcuts help modal
   */
  openHelp: () => void;

  /**
   * Close the shortcuts help modal
   */
  closeHelp: () => void;

  /**
   * Toggle the shortcuts help modal
   */
  toggleHelp: () => void;

  /**
   * Set a custom key binding for a shortcut
   */
  setCustomBinding: (shortcutId: string, bindings: KeyBinding[]) => void;

  /**
   * Clear a custom key binding (revert to default)
   */
  clearCustomBinding: (shortcutId: string) => void;

  /**
   * Disable a specific shortcut
   */
  disableShortcut: (shortcutId: string) => void;

  /**
   * Enable a specific shortcut
   */
  enableShortcut: (shortcutId: string) => void;

  /**
   * Add a key to the pending sequence
   */
  addToSequence: (key: string) => void;

  /**
   * Clear the pending key sequence
   */
  clearSequence: () => void;

  /**
   * Set the current shortcut context
   */
  setContext: (context: 'global' | 'debate' | 'list' | 'editor') => void;

  /**
   * Reset all shortcuts to defaults
   */
  resetToDefaults: () => void;
}

type ShortcutsStore = ShortcutsState & ShortcutsActions;

// ============================================================================
// Initial State
// ============================================================================

const initialState: ShortcutsState = {
  enabled: true,
  customBindings: {},
  disabledShortcuts: [],
  isHelpOpen: false,
  pendingSequence: [],
  sequenceStartTime: null,
  currentContext: 'global',
};

// ============================================================================
// Store
// ============================================================================

export const useShortcutsStore = create<ShortcutsStore>()(
  devtools(
    persist(
      (set) => ({
        // Initial state
        ...initialState,

        // Actions
        setEnabled: (enabled) => set({ enabled }, false, 'setEnabled'),

        toggleEnabled: () => set((state) => ({ enabled: !state.enabled }), false, 'toggleEnabled'),

        openHelp: () => set({ isHelpOpen: true }, false, 'openHelp'),

        closeHelp: () => set({ isHelpOpen: false }, false, 'closeHelp'),

        toggleHelp: () => set((state) => ({ isHelpOpen: !state.isHelpOpen }), false, 'toggleHelp'),

        setCustomBinding: (shortcutId, bindings) =>
          set(
            (state) => ({ customBindings: { ...state.customBindings, [shortcutId]: bindings } }),
            false,
            'setCustomBinding',
          ),

        clearCustomBinding: (shortcutId) =>
          set(
            (state) => {
              const { [shortcutId]: _, ...rest } = state.customBindings;
              return { customBindings: rest };
            },
            false,
            'clearCustomBinding',
          ),

        disableShortcut: (shortcutId) =>
          set(
            (state) => ({
              disabledShortcuts: state.disabledShortcuts.includes(shortcutId)
                ? state.disabledShortcuts
                : [...state.disabledShortcuts, shortcutId],
            }),
            false,
            'disableShortcut',
          ),

        enableShortcut: (shortcutId) =>
          set(
            (state) => ({
              disabledShortcuts: state.disabledShortcuts.filter((id) => id !== shortcutId),
            }),
            false,
            'enableShortcut',
          ),

        addToSequence: (key) =>
          set(
            (state) => ({
              pendingSequence: [...state.pendingSequence, key],
              sequenceStartTime: state.sequenceStartTime ?? Date.now(),
            }),
            false,
            'addToSequence',
          ),

        clearSequence: () =>
          set({ pendingSequence: [], sequenceStartTime: null }, false, 'clearSequence'),

        setContext: (context) => set({ currentContext: context }, false, 'setContext'),

        resetToDefaults: () =>
          set(
            { enabled: true, customBindings: {}, disabledShortcuts: [] },
            false,
            'resetToDefaults',
          ),
      }),
      {
        name: 'aragora-shortcuts',
        // Only persist user preferences, not runtime state
        partialize: (state) => ({
          enabled: state.enabled,
          customBindings: state.customBindings,
          disabledShortcuts: state.disabledShortcuts,
        }),
      },
    ),
    { name: 'shortcuts-store' },
  ),
);

// ============================================================================
// Selectors
// ============================================================================

/**
 * Select whether shortcuts are enabled
 */
export const selectShortcutsEnabled = (state: ShortcutsStore) => state.enabled;

/**
 * Select whether the help modal is open
 */
export const selectHelpOpen = (state: ShortcutsStore) => state.isHelpOpen;

/**
 * Select the current pending sequence
 */
export const selectPendingSequence = (state: ShortcutsStore) => state.pendingSequence;

/**
 * Select the current context
 */
export const selectCurrentContext = (state: ShortcutsStore) => state.currentContext;

/**
 * Check if a specific shortcut is disabled
 */
export const selectIsShortcutDisabled = (state: ShortcutsStore, shortcutId: string) =>
  state.disabledShortcuts.includes(shortcutId);

/**
 * Get custom bindings for a shortcut
 */
export const selectCustomBinding = (state: ShortcutsStore, shortcutId: string) =>
  state.customBindings[shortcutId];
