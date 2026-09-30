'use client';

import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';
import { useCommandPaletteStore } from '@/store/commandPaletteStore';
import { useUIStore } from '@/store/uiStore';

interface CommandPaletteContextValue {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

const CommandPaletteContext = createContext<CommandPaletteContextValue | null>(null);

interface CommandPaletteProviderProps {
  children: ReactNode;
}

/**
 * CommandPaletteProvider
 *
 * Provides global keyboard shortcut registration for opening the command palette.
 * Handles Cmd+K (Mac) / Ctrl+K (Windows/Linux) keyboard shortcuts.
 */
export function CommandPaletteProvider({ children }: CommandPaletteProviderProps) {
  const { isOpen, open, close, toggle } = useCommandPaletteStore();
  const keyboardShortcutsEnabled = useUIStore((state) => state.keyboardShortcutsEnabled);

  // Global keyboard shortcut registration
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd+K (Mac) or Ctrl+K (Windows/Linux) to toggle
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        e.stopPropagation();
        toggle();
        return;
      }

      // Allow Escape to work even when shortcuts disabled (for closing)
      if (e.key === 'Escape' && isOpen) {
        e.preventDefault();
        close();
        return;
      }

      // Skip other shortcuts if disabled (e.g., when typing in an input)
      if (!keyboardShortcutsEnabled && !isOpen) return;
    };

    // Use capture phase to intercept before other handlers
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [isOpen, toggle, close, keyboardShortcutsEnabled]);

  const value = useMemo<CommandPaletteContextValue>(
    () => ({ isOpen, open, close, toggle }),
    [isOpen, open, close, toggle],
  );

  return <CommandPaletteContext.Provider value={value}>{children}</CommandPaletteContext.Provider>;
}

/**
 * Hook to access command palette context
 */
export function useCommandPalette(): CommandPaletteContextValue {
  const context = useContext(CommandPaletteContext);
  if (!context) {
    throw new Error('useCommandPalette must be used within a CommandPaletteProvider');
  }
  return context;
}

export default CommandPaletteProvider;
