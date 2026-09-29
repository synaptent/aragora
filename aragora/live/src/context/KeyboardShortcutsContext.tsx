'use client';

import {
  createContext,
  useContext,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  type ReactNode,
} from 'react';
import { useRouter } from 'next/navigation';
import { useShortcutsStore } from '@/store/shortcutsStore';
import { useUIStore } from '@/store/uiStore';
import { useCommandPaletteStore } from '@/store/commandPaletteStore';
import { logger } from '@/utils/logger';
import {
  DEFAULT_SHORTCUTS,
  parseKeyEvent,
  isInputFocused,
  findMatchingShortcut,
  SEQUENCE_TIMEOUT_MS,
  type ShortcutWithAction,
} from '@/lib/shortcuts';

// ============================================================================
// Context Types
// ============================================================================

interface KeyboardShortcutsContextValue {
  /**
   * Whether shortcuts are enabled
   */
  isEnabled: boolean;

  /**
   * Whether the help modal is open
   */
  isHelpOpen: boolean;

  /**
   * Open the shortcuts help modal
   */
  openHelp: () => void;

  /**
   * Close the shortcuts help modal
   */
  closeHelp: () => void;

  /**
   * Toggle shortcuts enabled state
   */
  toggleEnabled: () => void;

  /**
   * Set the current shortcut context
   */
  setContext: (context: 'global' | 'debate' | 'list' | 'editor') => void;

  /**
   * All registered shortcuts with their actions
   */
  shortcuts: ShortcutWithAction[];
}

const KeyboardShortcutsContext = createContext<KeyboardShortcutsContextValue | null>(null);

// ============================================================================
// Provider Props
// ============================================================================

interface KeyboardShortcutsProviderProps {
  children: ReactNode;
}

// ============================================================================
// Provider Component
// ============================================================================

/**
 * KeyboardShortcutsProvider
 *
 * Provides Gmail-style keyboard shortcuts throughout the application.
 * Handles:
 * - Single-key shortcuts (c for compose)
 * - Sequence shortcuts (g then i for go to inbox)
 * - Modifier shortcuts (Cmd+\ for toggle sidebar)
 * - Help modal (? key)
 */
export function KeyboardShortcutsProvider({ children }: KeyboardShortcutsProviderProps) {
  const router = useRouter();

  // Store state
  const {
    enabled,
    isHelpOpen,
    pendingSequence,
    sequenceStartTime,
    currentContext,
    disabledShortcuts,
    openHelp,
    closeHelp,
    toggleEnabled,
    addToSequence,
    clearSequence,
    setContext,
  } = useShortcutsStore();

  const keyboardShortcutsEnabled = useUIStore((state) => state.keyboardShortcutsEnabled);
  const togglePanel = useUIStore((state) => state.togglePanel);
  const commandPaletteToggle = useCommandPaletteStore((state) => state.toggle);
  const commandPaletteIsOpen = useCommandPaletteStore((state) => state.isOpen);

  // Timeout ref for sequence clearing
  const sequenceTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Build shortcuts with actions
  const shortcuts: ShortcutWithAction[] = DEFAULT_SHORTCUTS.map((shortcut) => {
    // Skip disabled shortcuts
    const isDisabled = disabledShortcuts.includes(shortcut.id);

    return {
      ...shortcut,
      enabled: shortcut.enabled !== false && !isDisabled,
      action: () => executeShortcut(shortcut.id),
    };
  });

  // Execute a shortcut action by ID
  const executeShortcut = useCallback(
    (id: string) => {
      switch (id) {
        // Navigation shortcuts
        case 'nav-hub':
          router.push('/hub');
          break;
        case 'nav-debates':
          router.push('/debates');
          break;
        case 'nav-analytics':
          router.push('/analytics');
          break;
        case 'nav-settings':
          router.push('/settings');
          break;
        case 'nav-knowledge':
          router.push('/knowledge');
          break;
        case 'nav-leaderboard':
          router.push('/leaderboard');
          break;
        case 'nav-templates':
          router.push('/templates');
          break;
        case 'nav-workflows':
          router.push('/workflows');
          break;
        case 'nav-control-plane':
          router.push('/control-plane');
          break;
        case 'nav-receipts':
          router.push('/receipts');
          break;
        case 'nav-insights':
          router.push('/insights');
          break;
        case 'nav-agents':
          router.push('/agents');
          break;
        case 'nav-intelligence':
          router.push('/intelligence');
          break;

        // Compose shortcuts
        case 'compose-debate':
          router.push('/arena');
          break;
        case 'compose-stress-test':
          router.push('/gauntlet');
          break;

        // Application shortcuts
        case 'app-search':
          commandPaletteToggle();
          break;
        case 'app-help':
          if (isHelpOpen) {
            closeHelp();
          } else {
            openHelp();
          }
          break;
        case 'app-close':
          // Close any open modal
          if (isHelpOpen) {
            closeHelp();
          }
          break;
        case 'app-toggle-sidebar':
          togglePanel('sidebar');
          break;
        case 'app-toggle-right-panel':
          togglePanel('eventsPanel');
          break;

        // List navigation (context-dependent)
        case 'list-back':
          router.back();
          break;

        // Pipeline shortcuts (handled by page-level useEffect in pipeline page)
        case 'pipeline-execute':
        case 'pipeline-new':
        case 'pipeline-save':
          break;

        // TODO: Implement debate-specific and list-specific shortcuts
        // These need to be wired up to the actual components
        default:
          logger.debug(`Shortcut not implemented: ${id}`);
      }
    },
    [router, commandPaletteToggle, isHelpOpen, openHelp, closeHelp, togglePanel],
  );

  // Clear sequence after timeout
  useEffect(() => {
    if (pendingSequence.length > 0 && sequenceStartTime) {
      const elapsed = Date.now() - sequenceStartTime;
      const remaining = SEQUENCE_TIMEOUT_MS - elapsed;

      if (remaining <= 0) {
        clearSequence();
      } else {
        sequenceTimeoutRef.current = setTimeout(() => {
          clearSequence();
        }, remaining);
      }
    }

    return () => {
      if (sequenceTimeoutRef.current) {
        clearTimeout(sequenceTimeoutRef.current);
      }
    };
  }, [pendingSequence, sequenceStartTime, clearSequence]);

  // Main keyboard event handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Skip if command palette is handling Cmd+K
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        return; // Let CommandPaletteContext handle this
      }

      // Always allow Escape to close modals
      if (e.key === 'Escape') {
        if (isHelpOpen) {
          e.preventDefault();
          closeHelp();
          return;
        }
        // Let other handlers process Escape
        return;
      }

      // Skip if shortcuts are disabled globally
      if (!enabled || !keyboardShortcutsEnabled) return;

      // Skip if command palette is open (let it handle its own shortcuts)
      if (commandPaletteIsOpen) return;

      // Skip if typing in an input field
      if (isInputFocused()) return;

      // Parse the key event
      const parsed = parseKeyEvent(e);

      // Find matching shortcut
      const match = findMatchingShortcut(parsed, shortcuts, pendingSequence, currentContext);

      if (match.shortcut) {
        // Full match - execute the shortcut
        e.preventDefault();
        e.stopPropagation();
        clearSequence();
        match.shortcut.action();
      } else if (match.isPendingSequence) {
        // Partial match - add to sequence
        e.preventDefault();
        e.stopPropagation();
        addToSequence(parsed.key);
      } else if (pendingSequence.length > 0) {
        // No match but we had a pending sequence - clear it
        clearSequence();
      }
    };

    // Use capture phase to intercept before other handlers
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [
    enabled,
    keyboardShortcutsEnabled,
    commandPaletteIsOpen,
    isHelpOpen,
    pendingSequence,
    currentContext,
    shortcuts,
    closeHelp,
    clearSequence,
    addToSequence,
  ]);

  // Context value
  const value = useMemo<KeyboardShortcutsContextValue>(
    () => ({
      isEnabled: enabled,
      isHelpOpen,
      openHelp,
      closeHelp,
      toggleEnabled,
      setContext,
      shortcuts,
    }),
    [enabled, isHelpOpen, openHelp, closeHelp, toggleEnabled, setContext, shortcuts],
  );

  return (
    <KeyboardShortcutsContext.Provider value={value}>{children}</KeyboardShortcutsContext.Provider>
  );
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook to access keyboard shortcuts context
 */
export function useKeyboardShortcuts(): KeyboardShortcutsContextValue {
  const context = useContext(KeyboardShortcutsContext);
  if (!context) {
    throw new Error('useKeyboardShortcuts must be used within a KeyboardShortcutsProvider');
  }
  return context;
}

export default KeyboardShortcutsProvider;
