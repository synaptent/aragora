'use client';

import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react';

/**
 * Context for sharing the currently selected debate ID across components.
 *
 * This eliminates prop drilling for components that need to know which
 * debate is currently active (analysis panels, metrics, etc.).
 *
 * @example
 * ```tsx
 * // In a provider (e.g., layout)
 * <DebateSelectionProvider>
 *   <App />
 * </DebateSelectionProvider>
 *
 * // In any component
 * const { debateId, setDebateId } = useDebateSelection();
 * ```
 */

export interface DebateMetadata {
  title?: string;
  question?: string;
  status?: 'pending' | 'streaming' | 'complete' | 'error';
  agentCount?: number;
  messageCount?: number;
  startedAt?: string;
  completedAt?: string;
}

export interface DebateSelectionContextValue {
  /** Currently selected debate ID (null if none) */
  debateId: string | null;
  /** Metadata about the selected debate */
  metadata: DebateMetadata | null;
  /** Whether a debate is currently selected */
  hasSelection: boolean;
  /** Whether the selected debate is a live/streaming debate */
  isLiveDebate: boolean;
  /** Set the selected debate ID */
  setDebateId: (id: string | null) => void;
  /** Update metadata for the current debate */
  updateMetadata: (metadata: Partial<DebateMetadata>) => void;
  /** Clear the selection */
  clearSelection: () => void;
  /** History of recently viewed debate IDs */
  recentDebates: string[];
  /** Add a debate to recent history */
  addToRecent: (id: string) => void;
}

const DebateSelectionContext = createContext<DebateSelectionContextValue | null>(null);

const RECENT_DEBATES_KEY = 'aragora_recent_debates';
const MAX_RECENT_DEBATES = 10;

function loadRecentDebates(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const stored = localStorage.getItem(RECENT_DEBATES_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveRecentDebates(debates: string[]): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(RECENT_DEBATES_KEY, JSON.stringify(debates.slice(0, MAX_RECENT_DEBATES)));
  } catch {
    // Ignore storage errors
  }
}

export interface DebateSelectionProviderProps {
  children: ReactNode;
  /** Initial debate ID (e.g., from URL params) */
  initialDebateId?: string | null;
}

export function DebateSelectionProvider({
  children,
  initialDebateId = null,
}: DebateSelectionProviderProps) {
  const [debateId, setDebateIdState] = useState<string | null>(initialDebateId);
  const [metadata, setMetadata] = useState<DebateMetadata | null>(null);
  const [recentDebates, setRecentDebates] = useState<string[]>(() => loadRecentDebates());

  const hasSelection = debateId !== null;
  const isLiveDebate = debateId?.startsWith('adhoc_') ?? false;

  const setDebateId = useCallback((id: string | null) => {
    setDebateIdState(id);
    if (id === null) {
      setMetadata(null);
    }
  }, []);

  const updateMetadata = useCallback((updates: Partial<DebateMetadata>) => {
    setMetadata((prev) => (prev ? { ...prev, ...updates } : updates));
  }, []);

  const clearSelection = useCallback(() => {
    setDebateIdState(null);
    setMetadata(null);
  }, []);

  const addToRecent = useCallback((id: string) => {
    setRecentDebates((prev) => {
      // Remove if already exists, add to front
      const filtered = prev.filter((d) => d !== id);
      const updated = [id, ...filtered].slice(0, MAX_RECENT_DEBATES);
      saveRecentDebates(updated);
      return updated;
    });
  }, []);

  const value = useMemo<DebateSelectionContextValue>(
    () => ({
      debateId,
      metadata,
      hasSelection,
      isLiveDebate,
      setDebateId,
      updateMetadata,
      clearSelection,
      recentDebates,
      addToRecent,
    }),
    [
      debateId,
      metadata,
      hasSelection,
      isLiveDebate,
      setDebateId,
      updateMetadata,
      clearSelection,
      recentDebates,
      addToRecent,
    ],
  );

  return (
    <DebateSelectionContext.Provider value={value}>{children}</DebateSelectionContext.Provider>
  );
}

export function useDebateSelection(): DebateSelectionContextValue {
  const context = useContext(DebateSelectionContext);
  if (!context) {
    throw new Error('useDebateSelection must be used within a DebateSelectionProvider');
  }
  return context;
}

/**
 * Hook that returns only the debate ID without throwing if outside provider.
 * Useful for components that can optionally use the context.
 */
export function useOptionalDebateSelection(): DebateSelectionContextValue | null {
  return useContext(DebateSelectionContext);
}

export default DebateSelectionContext;
