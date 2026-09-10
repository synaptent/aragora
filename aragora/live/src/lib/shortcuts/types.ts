/**
 * Keyboard Shortcuts Type Definitions
 *
 * Gmail-style keyboard shortcuts system for Aragora.
 */

/**
 * Categories for organizing shortcuts in the help modal
 */
export type ShortcutCategory =
  | 'navigation' // g+i, g+s, etc. - Go to pages
  | 'debates' // n, p, r, e, f, s - Debate actions
  | 'list' // j, k, o, x - List navigation
  | 'selection' // *, x - Selection actions
  | 'compose' // c - Create new items
  | 'application'; // ?, /, Escape - App-level shortcuts

/**
 * Human-readable category labels for display
 */
export const CATEGORY_LABELS: Record<ShortcutCategory, string> = {
  navigation: 'Navigation',
  debates: 'Debates',
  list: 'List Navigation',
  selection: 'Selection',
  compose: 'Compose & Chat',
  application: 'Application',
};

/**
 * Order for displaying categories in the help modal
 */
export const CATEGORY_ORDER: ShortcutCategory[] = [
  'navigation',
  'compose',
  'debates',
  'list',
  'selection',
  'application',
];

/**
 * Modifier keys for shortcuts
 */
export type ModifierKey = 'meta' | 'ctrl' | 'alt' | 'shift';

/**
 * Platform types for platform-specific shortcuts
 */
export type Platform = 'mac' | 'windows' | 'linux';

/**
 * Represents a keyboard shortcut binding
 * Can be a single key, sequence, or key with modifiers
 */
export interface KeyBinding {
  /**
   * The main key(s) for the shortcut
   * - Single key: 'c'
   * - Sequence: ['g', 'i']
   * - With modifiers: 'k' with modifiers: ['meta']
   */
  key: string | string[];

  /**
   * Modifier keys required (Cmd/Ctrl, Alt, Shift)
   */
  modifiers?: ModifierKey[];

  /**
   * Whether this is a sequence (g then i) vs chord (Cmd+K)
   */
  isSequence?: boolean;
}

/**
 * Definition for a single keyboard shortcut
 */
export interface ShortcutDefinition {
  /**
   * Unique identifier for the shortcut
   */
  id: string;

  /**
   * The key binding(s) for this shortcut
   * Can have multiple bindings (e.g., both '/' and 'Cmd+K' for search)
   */
  keys: KeyBinding | KeyBinding[];

  /**
   * Human-readable description shown in help modal
   */
  description: string;

  /**
   * Category for grouping in help modal
   */
  category: ShortcutCategory;

  /**
   * Whether this shortcut is currently enabled
   * @default true
   */
  enabled?: boolean;

  /**
   * Whether this shortcut requires authentication
   * @default false
   */
  requiresAuth?: boolean;

  /**
   * Platforms this shortcut is available on
   * @default all platforms
   */
  platforms?: Platform[];

  /**
   * Context where this shortcut is active
   * @default 'global'
   */
  context?: 'global' | 'debate' | 'list' | 'editor';

  /**
   * Priority for conflict resolution (higher wins)
   * @default 0
   */
  priority?: number;
}

/**
 * Shortcut with action callback attached
 */
export interface ShortcutWithAction extends ShortcutDefinition {
  /**
   * Action to execute when shortcut is triggered
   */
  action: () => void | Promise<void>;
}

/**
 * State for the keyboard shortcuts context
 */
export interface KeyboardShortcutsState {
  /**
   * Whether keyboard shortcuts are enabled globally
   */
  isEnabled: boolean;

  /**
   * Whether the help modal is currently open
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
}

/**
 * Actions for the keyboard shortcuts context
 */
export interface KeyboardShortcutsActions {
  /**
   * Toggle shortcuts enabled/disabled
   */
  setEnabled: (enabled: boolean) => void;

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
   * Register a shortcut with its action
   */
  registerShortcut: (shortcut: ShortcutWithAction) => void;

  /**
   * Unregister a shortcut by ID
   */
  unregisterShortcut: (id: string) => void;

  /**
   * Execute a shortcut by ID
   */
  executeShortcut: (id: string) => void;

  /**
   * Clear the pending key sequence
   */
  clearSequence: () => void;

  /**
   * Add a key to the pending sequence
   */
  addToSequence: (key: string) => void;
}

/**
 * Parsed key event for matching against shortcuts
 */
export interface ParsedKeyEvent {
  key: string;
  code: string;
  meta: boolean;
  ctrl: boolean;
  alt: boolean;
  shift: boolean;
}

/**
 * Result of matching a key event against shortcuts
 */
export interface ShortcutMatch {
  /**
   * The matched shortcut, if any
   */
  shortcut: ShortcutWithAction | null;

  /**
   * Whether we're in the middle of a sequence
   */
  isPendingSequence: boolean;

  /**
   * Possible shortcuts that could still match with more keys
   */
  possibleMatches: ShortcutWithAction[];
}

/**
 * User preferences for keyboard shortcuts
 */
export interface ShortcutsPreferences {
  /**
   * Whether shortcuts are enabled
   */
  enabled: boolean;

  /**
   * Custom key bindings (shortcut ID -> custom keys)
   */
  customBindings: Record<string, KeyBinding[]>;

  /**
   * Shortcuts that have been disabled by the user
   */
  disabledShortcuts: string[];
}

/**
 * Props for the KeyboardShortcutsHelp component
 */
export interface KeyboardShortcutsHelpProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Props for the ShortcutKey component (displays a key badge)
 */
export interface ShortcutKeyProps {
  /**
   * The key(s) to display
   */
  keys: KeyBinding;

  /**
   * Size variant
   */
  size?: 'sm' | 'md' | 'lg';

  /**
   * Additional CSS classes
   */
  className?: string;
}
