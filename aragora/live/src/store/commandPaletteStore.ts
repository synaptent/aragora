'use client';

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type {
  CommandPaletteStore,
  SearchCategory,
  SearchResult,
  RecentItem,
} from '@/components/command-palette/types';

const MAX_RECENT_ITEMS = 10;

export const useCommandPaletteStore = create<CommandPaletteStore>()(
  devtools(
    persist(
      (set, get) => ({
        // Initial state
        isOpen: false,
        query: '',
        activeCategory: 'all',
        selectedIndex: 0,
        results: [],
        isSearching: false,
        searchError: null,
        recentItems: [],

        // Modal actions
        open: () =>
          set(
            { isOpen: true, query: '', selectedIndex: 0, results: [], searchError: null },
            false,
            'open',
          ),

        close: () =>
          set(
            { isOpen: false, query: '', selectedIndex: 0, results: [], searchError: null },
            false,
            'close',
          ),

        toggle: () => {
          const { isOpen, open, close } = get();
          if (isOpen) {
            close();
          } else {
            open();
          }
        },

        // Search actions
        setQuery: (query: string) => set({ query, selectedIndex: 0 }, false, 'setQuery'),

        setActiveCategory: (category: SearchCategory) =>
          set({ activeCategory: category, selectedIndex: 0 }, false, 'setActiveCategory'),

        setSelectedIndex: (index: number) =>
          set({ selectedIndex: index }, false, 'setSelectedIndex'),

        // Results actions
        setResults: (results: SearchResult[]) =>
          set({ results, selectedIndex: 0 }, false, 'setResults'),

        setIsSearching: (isSearching: boolean) => set({ isSearching }, false, 'setIsSearching'),

        setSearchError: (error: string | null) =>
          set({ searchError: error }, false, 'setSearchError'),

        // Navigation actions
        moveUp: () => {
          const { selectedIndex, results, recentItems, query } = get();
          // When no query, include recent items in count
          const totalItems = query.trim() ? results.length : recentItems.length + results.length;
          if (totalItems === 0) return;

          const newIndex = selectedIndex <= 0 ? totalItems - 1 : selectedIndex - 1;
          set({ selectedIndex: newIndex }, false, 'moveUp');
        },

        moveDown: () => {
          const { selectedIndex, results, recentItems, query } = get();
          const totalItems = query.trim() ? results.length : recentItems.length + results.length;
          if (totalItems === 0) return;

          const newIndex = selectedIndex >= totalItems - 1 ? 0 : selectedIndex + 1;
          set({ selectedIndex: newIndex }, false, 'moveDown');
        },

        // Recent items actions
        addRecentItem: (item: Omit<RecentItem, 'timestamp'>) => {
          const { recentItems } = get();

          // Remove existing item with same id if present
          const filtered = recentItems.filter((r) => r.id !== item.id);

          // Add new item at the beginning
          const newItem: RecentItem = { ...item, timestamp: Date.now() };

          // Keep only MAX_RECENT_ITEMS
          const updated = [newItem, ...filtered].slice(0, MAX_RECENT_ITEMS);

          set({ recentItems: updated }, false, 'addRecentItem');
        },

        removeRecentItem: (id: string) => {
          const { recentItems } = get();
          set({ recentItems: recentItems.filter((r) => r.id !== id) }, false, 'removeRecentItem');
        },

        clearRecentItems: () => set({ recentItems: [] }, false, 'clearRecentItems'),

        // Reset
        reset: () =>
          set(
            {
              isOpen: false,
              query: '',
              activeCategory: 'all',
              selectedIndex: 0,
              results: [],
              isSearching: false,
              searchError: null,
            },
            false,
            'reset',
          ),
      }),
      {
        name: 'aragora-command-palette',
        // Only persist recent items
        partialize: (state) => ({ recentItems: state.recentItems }),
      },
    ),
    { name: 'command-palette-store' },
  ),
);

// Selectors
export const selectIsOpen = (state: CommandPaletteStore) => state.isOpen;
export const selectQuery = (state: CommandPaletteStore) => state.query;
export const selectActiveCategory = (state: CommandPaletteStore) => state.activeCategory;
export const selectSelectedIndex = (state: CommandPaletteStore) => state.selectedIndex;
export const selectResults = (state: CommandPaletteStore) => state.results;
export const selectIsSearching = (state: CommandPaletteStore) => state.isSearching;
export const selectSearchError = (state: CommandPaletteStore) => state.searchError;
export const selectRecentItems = (state: CommandPaletteStore) => state.recentItems;
