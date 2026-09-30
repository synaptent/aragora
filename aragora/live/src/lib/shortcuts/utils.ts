/**
 * Keyboard Shortcuts Utilities
 *
 * Helper functions for key parsing, platform detection, and shortcut matching.
 */

import type {
  KeyBinding,
  ModifierKey,
  ParsedKeyEvent,
  Platform,
  ShortcutWithAction,
  ShortcutMatch,
} from './types';

/**
 * Sequence timeout in milliseconds
 * After this time, pending sequence is cleared
 */
export const SEQUENCE_TIMEOUT_MS = 1500;

/**
 * Detect the current platform
 */
export function getPlatform(): Platform {
  if (typeof navigator === 'undefined') return 'windows';

  const platform = navigator.platform?.toLowerCase() || '';
  const userAgent = navigator.userAgent?.toLowerCase() || '';

  if (platform.includes('mac') || userAgent.includes('mac')) {
    return 'mac';
  }
  if (platform.includes('linux') || userAgent.includes('linux')) {
    return 'linux';
  }
  return 'windows';
}

/**
 * Check if we're on a Mac
 */
export function isMac(): boolean {
  return getPlatform() === 'mac';
}

/**
 * Get the appropriate modifier key for the platform
 * Mac uses Cmd (meta), Windows/Linux use Ctrl
 */
export function getPrimaryModifier(): ModifierKey {
  return isMac() ? 'meta' : 'ctrl';
}

/**
 * Parse a keyboard event into a normalized structure
 */
export function parseKeyEvent(event: KeyboardEvent): ParsedKeyEvent {
  return {
    key: event.key.toLowerCase(),
    code: event.code,
    meta: event.metaKey,
    ctrl: event.ctrlKey,
    alt: event.altKey,
    shift: event.shiftKey,
  };
}

/**
 * Check if the currently focused element is an input
 * Shortcuts should not trigger when typing in inputs
 */
export function isInputFocused(): boolean {
  const activeElement = document.activeElement;
  if (!activeElement) return false;

  const tagName = activeElement.tagName.toLowerCase();
  const isInput = tagName === 'input' || tagName === 'textarea' || tagName === 'select';
  const isContentEditable = activeElement.getAttribute('contenteditable') === 'true';
  const isRichEditor = activeElement.closest('[role="textbox"]') !== null;

  return isInput || isContentEditable || isRichEditor;
}

/**
 * Check if a key event matches a key binding
 */
export function matchesKeyBinding(
  event: ParsedKeyEvent,
  binding: KeyBinding,
  pendingSequence: string[],
): 'match' | 'partial' | 'none' {
  const keys = Array.isArray(binding.key) ? binding.key : [binding.key];
  const modifiers = binding.modifiers || [];
  const isSequence = binding.isSequence ?? keys.length > 1;

  // Check modifiers for non-sequence shortcuts
  if (!isSequence || keys.length === 1) {
    const modifiersMatch =
      (modifiers.includes('meta') === event.meta || (modifiers.includes('ctrl') && event.ctrl)) &&
      (modifiers.includes('ctrl') === event.ctrl || (modifiers.includes('meta') && event.meta)) &&
      modifiers.includes('alt') === event.alt &&
      modifiers.includes('shift') === event.shift;

    // For single key with modifiers (like Cmd+K)
    if (!isSequence && modifiers.length > 0) {
      if (!modifiersMatch) return 'none';
      return keys[0] === event.key ? 'match' : 'none';
    }

    // For single key without modifiers (like 'c')
    if (keys.length === 1 && modifiers.length === 0) {
      // Don't match if any modifiers are pressed (except shift for special chars)
      if (event.meta || event.ctrl || event.alt) return 'none';
      return keys[0] === event.key ? 'match' : 'none';
    }
  }

  // Sequence matching (like g+i)
  if (isSequence) {
    const fullSequence = [...pendingSequence, event.key];

    // Check if the full sequence matches
    if (fullSequence.length === keys.length) {
      const matches = keys.every((k, i) => k === fullSequence[i]);
      return matches ? 'match' : 'none';
    }

    // Check if we're building towards this sequence
    if (fullSequence.length < keys.length) {
      const matchesSoFar = fullSequence.every((k, i) => k === keys[i]);
      return matchesSoFar ? 'partial' : 'none';
    }
  }

  return 'none';
}

/**
 * Find matching shortcuts for a key event
 */
export function findMatchingShortcut(
  event: ParsedKeyEvent,
  shortcuts: ShortcutWithAction[],
  pendingSequence: string[],
  context: string = 'global',
): ShortcutMatch {
  let matchedShortcut: ShortcutWithAction | null = null;
  const possibleMatches: ShortcutWithAction[] = [];

  for (const shortcut of shortcuts) {
    // Skip disabled shortcuts
    if (shortcut.enabled === false) continue;

    // Check platform compatibility
    if (shortcut.platforms && !shortcut.platforms.includes(getPlatform())) continue;

    // Check context
    if (shortcut.context && shortcut.context !== 'global' && shortcut.context !== context) {
      continue;
    }

    const bindings = Array.isArray(shortcut.keys) ? shortcut.keys : [shortcut.keys];

    for (const binding of bindings) {
      const result = matchesKeyBinding(event, binding, pendingSequence);

      if (result === 'match') {
        // Higher priority wins
        if (!matchedShortcut || (shortcut.priority || 0) > (matchedShortcut.priority || 0)) {
          matchedShortcut = shortcut;
        }
      } else if (result === 'partial') {
        possibleMatches.push(shortcut);
      }
    }
  }

  return {
    shortcut: matchedShortcut,
    isPendingSequence: possibleMatches.length > 0 && !matchedShortcut,
    possibleMatches,
  };
}

/**
 * Format a key binding for display in the UI
 */
export function formatKeyBinding(binding: KeyBinding): string {
  const keys = Array.isArray(binding.key) ? binding.key : [binding.key];
  const modifiers = binding.modifiers || [];
  const isSequence = binding.isSequence ?? keys.length > 1;
  const mac = isMac();

  const modifierSymbols: Record<ModifierKey, string> = mac
    ? { meta: '\u2318', ctrl: '\u2303', alt: '\u2325', shift: '\u21E7' }
    : { meta: 'Win', ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift' };

  const formattedModifiers = modifiers.map((m) => modifierSymbols[m]).join(mac ? '' : '+');

  if (isSequence) {
    return keys.map((k) => formatSingleKey(k)).join(' then ');
  }

  const formattedKey = formatSingleKey(keys[0]);

  if (modifiers.length > 0) {
    return mac ? `${formattedModifiers}${formattedKey}` : `${formattedModifiers}+${formattedKey}`;
  }

  return formattedKey;
}

/**
 * Format a single key for display
 */
function formatSingleKey(key: string): string {
  const specialKeys: Record<string, string> = {
    escape: 'Esc',
    enter: 'Enter',
    ' ': 'Space',
    arrowup: '\u2191',
    arrowdown: '\u2193',
    arrowleft: '\u2190',
    arrowright: '\u2192',
    backspace: '\u232B',
    delete: '\u2326',
    tab: '\u21E5',
  };

  const normalized = key.toLowerCase();
  return specialKeys[normalized] || key.toUpperCase();
}

/**
 * Check if a shortcut should be shown based on platform
 */
export function isShortcutAvailable(shortcut: ShortcutWithAction): boolean {
  if (!shortcut.platforms) return true;
  return shortcut.platforms.includes(getPlatform());
}

/**
 * Group shortcuts by category for display
 */
export function groupShortcutsByCategory(
  shortcuts: ShortcutWithAction[],
): Map<string, ShortcutWithAction[]> {
  const groups = new Map<string, ShortcutWithAction[]>();

  for (const shortcut of shortcuts) {
    if (!isShortcutAvailable(shortcut)) continue;
    if (shortcut.enabled === false) continue;

    const category = shortcut.category;
    if (!groups.has(category)) {
      groups.set(category, []);
    }
    groups.get(category)!.push(shortcut);
  }

  return groups;
}

/**
 * Create a simple key binding (single key, no modifiers)
 */
export function key(k: string): KeyBinding {
  return { key: k };
}

/**
 * Create a sequence key binding (e.g., g then i)
 */
export function sequence(...keys: string[]): KeyBinding {
  return { key: keys, isSequence: true };
}

/**
 * Create a key binding with modifiers
 */
export function withModifiers(k: string, ...mods: ModifierKey[]): KeyBinding {
  return { key: k, modifiers: mods };
}

/**
 * Create a Cmd/Ctrl+key binding (platform-aware)
 */
export function cmdKey(k: string): KeyBinding {
  return { key: k, modifiers: [getPrimaryModifier()] };
}

/**
 * Create a Cmd/Ctrl+Shift+key binding (platform-aware)
 */
export function cmdShiftKey(k: string): KeyBinding {
  return { key: k, modifiers: [getPrimaryModifier(), 'shift'] };
}
