/**
 * Command Palette Types
 *
 * Type definitions for the global command palette (Cmd+K)
 */

export type SearchCategory =
  'all' | 'debates' | 'agents' | 'documents' | 'knowledge' | 'pages' | 'actions';

export interface SearchResult {
  id: string;
  type: SearchCategory;
  title: string;
  subtitle?: string;
  href?: string;
  action?: () => void;
  icon?: string;
  score?: number;
  keywords?: string[];
  metadata?: Record<string, unknown>;
}

export interface RecentItem {
  id: string;
  type: SearchCategory;
  title: string;
  subtitle?: string;
  href?: string;
  icon?: string;
  timestamp: number;
}

export interface QuickAction {
  id: string;
  label: string;
  shortcut?: string;
  icon: string;
  href?: string;
  action?: () => void;
  keywords: string[];
  description?: string;
}

export interface CommandPaletteState {
  // Modal state
  isOpen: boolean;

  // Search state
  query: string;
  activeCategory: SearchCategory;
  selectedIndex: number;

  // Results
  results: SearchResult[];
  isSearching: boolean;
  searchError: string | null;

  // Recent items (persisted)
  recentItems: RecentItem[];
}

export interface CommandPaletteActions {
  // Modal
  open: () => void;
  close: () => void;
  toggle: () => void;

  // Search
  setQuery: (query: string) => void;
  setActiveCategory: (category: SearchCategory) => void;
  setSelectedIndex: (index: number) => void;

  // Results
  setResults: (results: SearchResult[]) => void;
  setIsSearching: (loading: boolean) => void;
  setSearchError: (error: string | null) => void;

  // Navigation
  moveUp: () => void;
  moveDown: () => void;

  // Recent items
  addRecentItem: (item: Omit<RecentItem, 'timestamp'>) => void;
  removeRecentItem: (id: string) => void;
  clearRecentItems: () => void;

  // Reset
  reset: () => void;
}

export type CommandPaletteStore = CommandPaletteState & CommandPaletteActions;

/**
 * Category configuration for UI display
 */
export interface CategoryConfig {
  id: SearchCategory;
  label: string;
  icon: string;
  shortcut?: string;
}

export const CATEGORIES: CategoryConfig[] = [
  { id: 'all', label: 'All', icon: '*', shortcut: 'A' },
  { id: 'pages', label: 'Pages', icon: '#', shortcut: 'P' },
  { id: 'debates', label: 'Debates', icon: '!', shortcut: 'D' },
  { id: 'agents', label: 'Agents', icon: '&', shortcut: 'G' },
  { id: 'documents', label: 'Docs', icon: ']', shortcut: 'O' },
  { id: 'knowledge', label: 'Knowledge', icon: '?', shortcut: 'K' },
  { id: 'actions', label: 'Actions', icon: '>', shortcut: 'X' },
];

/**
 * Quick actions available in the palette
 */
export const QUICK_ACTIONS: QuickAction[] = [
  {
    id: 'new-debate',
    label: 'New Debate',
    icon: '!',
    href: '/arena',
    keywords: ['create', 'start', 'debate', 'new'],
    description: 'Start a new AI debate',
  },
  {
    id: 'stress-test',
    label: 'Stress Test',
    icon: '%',
    href: '/gauntlet',
    keywords: ['gauntlet', 'stress', 'test', 'challenge'],
    description: 'Run a decision stress test',
  },
  {
    id: 'code-review',
    label: 'Code Review',
    icon: '<',
    href: '/reviews',
    keywords: ['code', 'review', 'security', 'audit'],
    description: 'Start a code security review',
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: '*',
    href: '/settings',
    keywords: ['settings', 'config', 'preferences', 'options'],
    description: 'Open settings panel',
  },
  {
    id: 'knowledge-base',
    label: 'Knowledge Base',
    icon: '?',
    href: '/knowledge',
    keywords: ['knowledge', 'search', 'kb', 'facts'],
    description: 'Search knowledge base',
  },
  {
    id: 'leaderboard',
    label: 'Leaderboard',
    icon: '^',
    href: '/leaderboard',
    keywords: ['leaderboard', 'ranking', 'elo', 'agents', 'scores'],
    description: 'View agent leaderboard',
  },
  {
    id: 'documents',
    label: 'Documents',
    icon: ']',
    href: '/documents',
    keywords: ['documents', 'files', 'upload', 'manage'],
    description: 'Manage documents',
  },
  {
    id: 'hub',
    label: 'Hub',
    icon: '+',
    href: '/hub',
    keywords: ['hub', 'home', 'main', 'start'],
    description: 'Go to hub',
  },
  {
    id: 'analytics',
    label: 'Analytics',
    icon: '~',
    href: '/analytics',
    keywords: ['analytics', 'stats', 'metrics', 'data'],
    description: 'View analytics dashboard',
  },
  {
    id: 'integrations',
    label: 'Integrations',
    icon: ':',
    href: '/integrations',
    keywords: ['integrations', 'slack', 'teams', 'connect'],
    description: 'Manage integrations',
  },
];
