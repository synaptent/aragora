'use client';

import { type KeyBinding, formatKeyBinding, isMac } from '@/lib/shortcuts';

interface ShortcutKeyProps {
  /**
   * The key binding to display
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

/**
 * ShortcutKey
 *
 * Displays a keyboard shortcut as styled key badges.
 * Adapts to platform (Mac uses symbols, Windows uses text).
 */
export function ShortcutKey({ keys, size = 'md', className = '' }: ShortcutKeyProps) {
  const formatted = formatKeyBinding(keys);
  const isSequence = keys.isSequence || (Array.isArray(keys.key) && keys.key.length > 1);

  // Size classes
  const sizeClasses = {
    sm: 'text-[10px] px-1 py-0.5 min-w-[18px]',
    md: 'text-xs px-1.5 py-0.5 min-w-[22px]',
    lg: 'text-sm px-2 py-1 min-w-[26px]',
  };

  const baseClasses = `
    inline-flex items-center justify-center
    font-theme-data font-medium
    bg-surface border border-[var(--accent)]/30
    text-text-muted
    rounded
    ${sizeClasses[size]}
  `;

  // For sequences, split and render each key separately
  if (isSequence) {
    const parts = formatted.split(' then ');
    return (
      <span className={`inline-flex items-center gap-1 ${className}`}>
        {parts.map((part, i) => (
          <span key={i} className="inline-flex items-center gap-1">
            <kbd className={baseClasses}>{part}</kbd>
            {i < parts.length - 1 && <span className="text-text-muted text-xs">then</span>}
          </span>
        ))}
      </span>
    );
  }

  // For modifier combos on Mac, split the symbols
  const mac = isMac();
  const modifiers = keys.modifiers || [];

  if (mac && modifiers.length > 0) {
    // Mac: Show modifier symbols separately for cleaner look
    const modifierSymbols: Record<string, string> = {
      meta: '\u2318',
      ctrl: '\u2303',
      alt: '\u2325',
      shift: '\u21E7',
    };

    const keyPart = Array.isArray(keys.key) ? keys.key[0] : keys.key;

    return (
      <span className={`inline-flex items-center gap-0.5 ${className}`}>
        {modifiers.map((mod) => (
          <kbd key={mod} className={baseClasses}>
            {modifierSymbols[mod]}
          </kbd>
        ))}
        <kbd className={baseClasses}>{keyPart.toUpperCase()}</kbd>
      </span>
    );
  }

  // For Windows/Linux or single keys
  return <kbd className={`${baseClasses} ${className}`}>{formatted}</kbd>;
}

/**
 * ShortcutKeyInline
 *
 * A simpler inline display of a shortcut key, without the fancy styling.
 * Useful for tooltips and compact displays.
 */
export function ShortcutKeyInline({ keys }: { keys: KeyBinding }) {
  return <span className="text-text-muted font-theme-data text-xs">{formatKeyBinding(keys)}</span>;
}

export default ShortcutKey;
