/**
 * Keyboard Shortcuts Registry
 *
 * Defines all available keyboard shortcuts for Aragora.
 * Actions are attached when shortcuts are registered in the context.
 */

import type { ShortcutDefinition } from './types';
import { key, sequence, cmdKey, cmdShiftKey } from './utils';

/**
 * All available shortcuts in the application
 * Actions are attached dynamically when registered
 */
export const DEFAULT_SHORTCUTS: ShortcutDefinition[] = [
  // ============================================
  // NAVIGATION - Go to pages (g + key sequences)
  // ============================================
  { id: 'nav-hub', keys: sequence('g', 'i'), description: 'Go to Hub', category: 'navigation' },
  {
    id: 'nav-debates',
    keys: sequence('g', 'd'),
    description: 'Go to Debates',
    category: 'navigation',
  },
  {
    id: 'nav-analytics',
    keys: sequence('g', 'a'),
    description: 'Go to Analytics',
    category: 'navigation',
  },
  {
    id: 'nav-settings',
    keys: [sequence('g', 's'), cmdKey(',')],
    description: 'Go to Settings',
    category: 'navigation',
  },
  {
    id: 'nav-knowledge',
    keys: sequence('g', 'k'),
    description: 'Go to Knowledge',
    category: 'navigation',
  },
  {
    id: 'nav-leaderboard',
    keys: sequence('g', 'l'),
    description: 'Go to Leaderboard',
    category: 'navigation',
  },
  {
    id: 'nav-templates',
    keys: sequence('g', 't'),
    description: 'Go to Templates',
    category: 'navigation',
  },
  {
    id: 'nav-workflows',
    keys: sequence('g', 'w'),
    description: 'Go to Workflows',
    category: 'navigation',
  },
  {
    id: 'nav-control-plane',
    keys: sequence('g', 'c'),
    description: 'Go to Dashboard',
    category: 'navigation',
  },
  {
    id: 'nav-receipts',
    keys: sequence('g', 'r'),
    description: 'Go to Receipts',
    category: 'navigation',
  },
  {
    id: 'nav-insights',
    keys: sequence('g', 'n'),
    description: 'Go to Insights',
    category: 'navigation',
  },
  {
    id: 'nav-agents',
    keys: sequence('g', 'g'),
    description: 'Go to Agents',
    category: 'navigation',
  },
  {
    id: 'nav-intelligence',
    keys: sequence('g', 'o'),
    description: 'Go to Intelligence',
    category: 'navigation',
  },

  // ============================================
  // COMPOSE - Create new items
  // ============================================
  { id: 'compose-debate', keys: key('c'), description: 'New Debate', category: 'compose' },
  {
    id: 'compose-stress-test',
    keys: key('t'),
    description: 'Stress Test',
    category: 'compose',
    context: 'global',
  },

  // ============================================
  // APPLICATION - App-level shortcuts
  // ============================================
  {
    id: 'app-search',
    keys: [key('/'), cmdKey('k')],
    description: 'Search / Command Palette',
    category: 'application',
    priority: 10, // High priority to override other '/' handlers
  },
  {
    id: 'app-help',
    keys: key('?'),
    description: 'Show Keyboard Shortcuts',
    category: 'application',
    priority: 10,
  },
  {
    id: 'app-close',
    keys: key('escape'),
    description: 'Close Modal / Cancel',
    category: 'application',
    priority: 100, // Always process Escape
  },
  {
    id: 'app-toggle-sidebar',
    keys: cmdKey('\\'),
    description: 'Toggle Sidebar',
    category: 'application',
  },
  {
    id: 'app-toggle-right-panel',
    keys: cmdShiftKey('\\'),
    description: 'Toggle Right Panel',
    category: 'application',
  },

  // ============================================
  // DEBATES - Actions within a debate view
  // ============================================
  {
    id: 'debate-next-message',
    keys: key('n'),
    description: 'Next Message',
    category: 'debates',
    context: 'debate',
  },
  {
    id: 'debate-prev-message',
    keys: key('p'),
    description: 'Previous Message',
    category: 'debates',
    context: 'debate',
  },
  {
    id: 'debate-participate',
    keys: key('r'),
    description: 'Participate / Reply',
    category: 'debates',
    context: 'debate',
  },
  {
    id: 'debate-export',
    keys: key('e'),
    description: 'Export Debate',
    category: 'debates',
    context: 'debate',
  },
  {
    id: 'debate-fork',
    keys: key('f'),
    description: 'Fork Debate',
    category: 'debates',
    context: 'debate',
  },
  {
    id: 'debate-star',
    keys: key('s'),
    description: 'Star / Save Debate',
    category: 'debates',
    context: 'debate',
  },

  // ============================================
  // LIST - Navigation in list views
  // ============================================
  { id: 'list-next', keys: key('j'), description: 'Next Item', category: 'list', context: 'list' },
  {
    id: 'list-prev',
    keys: key('k'),
    description: 'Previous Item',
    category: 'list',
    context: 'list',
  },
  {
    id: 'list-open',
    keys: [key('o'), key('enter')],
    description: 'Open Item',
    category: 'list',
    context: 'list',
  },
  { id: 'list-back', keys: key('u'), description: 'Back to List', category: 'list' },

  // ============================================
  // SELECTION - Select items in lists
  // ============================================
  {
    id: 'select-toggle',
    keys: key('x'),
    description: 'Toggle Selection',
    category: 'selection',
    context: 'list',
  },
  {
    id: 'select-all',
    keys: sequence('*', 'a'),
    description: 'Select All',
    category: 'selection',
    context: 'list',
  },
  {
    id: 'select-none',
    keys: sequence('*', 'n'),
    description: 'Select None',
    category: 'selection',
    context: 'list',
  },

  // ============================================
  // PIPELINE - Pipeline canvas shortcuts
  // ============================================
  {
    id: 'pipeline-execute',
    keys: cmdKey('e'),
    description: 'Execute Pipeline',
    category: 'application',
  },
  {
    id: 'pipeline-new',
    keys: cmdShiftKey('n'),
    description: 'New Pipeline',
    category: 'application',
  },
  { id: 'pipeline-save', keys: cmdKey('s'), description: 'Save Pipeline', category: 'application' },
];

/**
 * Get a shortcut definition by ID
 */
export function getShortcutById(id: string): ShortcutDefinition | undefined {
  return DEFAULT_SHORTCUTS.find((s) => s.id === id);
}

/**
 * Get shortcuts by category
 */
export function getShortcutsByCategory(category: string): ShortcutDefinition[] {
  return DEFAULT_SHORTCUTS.filter((s) => s.category === category);
}

/**
 * Get global shortcuts (no specific context required)
 */
export function getGlobalShortcuts(): ShortcutDefinition[] {
  return DEFAULT_SHORTCUTS.filter((s) => !s.context || s.context === 'global');
}

/**
 * Get shortcuts for a specific context
 */
export function getContextShortcuts(context: string): ShortcutDefinition[] {
  return DEFAULT_SHORTCUTS.filter(
    (s) => s.context === context || s.context === 'global' || !s.context,
  );
}
