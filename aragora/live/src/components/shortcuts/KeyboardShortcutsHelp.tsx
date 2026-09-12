'use client';

import { useEffect, useRef } from 'react';
import { useShortcutsStore } from '@/store/shortcutsStore';
import { useKeyboardShortcuts } from '@/context/KeyboardShortcutsContext';
import { ShortcutKey } from './ShortcutKey';
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  groupShortcutsByCategory,
  type ShortcutCategory,
  type KeyBinding,
} from '@/lib/shortcuts';

/**
 * KeyboardShortcutsHelp
 *
 * A full-screen modal displaying all available keyboard shortcuts,
 * organized by category (similar to Gmail's keyboard shortcuts help).
 */
export function KeyboardShortcutsHelp() {
  const { isHelpOpen, closeHelp, shortcuts } = useKeyboardShortcuts();
  const { enabled, toggleEnabled } = useShortcutsStore();
  const modalRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        closeHelp();
      }
    };

    if (isHelpOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      // Prevent body scroll when modal is open
      document.body.style.overflow = 'hidden';
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.body.style.overflow = '';
    };
  }, [isHelpOpen, closeHelp]);

  if (!isHelpOpen) return null;

  // Group shortcuts by category
  const grouped = groupShortcutsByCategory(shortcuts);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-bg/90 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcuts-help-title"
    >
      <div
        ref={modalRef}
        className="
          relative
          w-full max-w-4xl max-h-[85vh]
          mx-4
          bg-surface border border-[var(--accent)]/30
          rounded-lg shadow-2xl
          overflow-hidden
          flex flex-col
        "
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--accent)]/20">
          <h2 id="shortcuts-help-title" className="text-lg font-theme-data text-[var(--accent)]">
            Keyboard Shortcuts
          </h2>
          <button
            onClick={closeHelp}
            className="
              text-text-muted hover:text-text
              transition-colors
              p-1
            "
            aria-label="Close shortcuts help"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {CATEGORY_ORDER.map((category) => {
              const categoryShortcuts = grouped.get(category);
              if (!categoryShortcuts || categoryShortcuts.length === 0) return null;

              return (
                <ShortcutCategory
                  key={category}
                  category={category}
                  shortcuts={categoryShortcuts}
                />
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[var(--accent)]/20 bg-bg/50">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={enabled}
              onChange={() => toggleEnabled()}
              className="
                w-4 h-4
                rounded
                border-[var(--accent)]/50
                bg-surface
                text-[var(--accent)]
                focus:ring-acid-green/50
                focus:ring-offset-0
              "
            />
            <span className="text-sm font-theme-data text-text-muted">
              Enable keyboard shortcuts
            </span>
          </label>
          <p className="mt-2 text-xs text-text-muted/70 font-theme-data">
            Press <ShortcutKey keys={{ key: '?' }} size="sm" /> anywhere to open this help. Press{' '}
            <ShortcutKey keys={{ key: 'escape' }} size="sm" /> to close.
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * ShortcutCategory
 *
 * Displays a group of shortcuts under a category heading.
 */
function ShortcutCategory({
  category,
  shortcuts,
}: {
  category: ShortcutCategory;
  shortcuts: Array<{ id: string; keys: KeyBinding | KeyBinding[]; description: string }>;
}) {
  return (
    <div>
      <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3 pb-2 border-b border-[var(--accent)]/20">
        {CATEGORY_LABELS[category]}
      </h3>
      <ul className="space-y-2">
        {shortcuts.map((shortcut) => {
          // Get the primary key binding (first one if array)
          const primaryKey = Array.isArray(shortcut.keys) ? shortcut.keys[0] : shortcut.keys;

          return (
            <li key={shortcut.id} className="flex items-center justify-between gap-4 text-sm">
              <span className="text-text-muted font-theme-data truncate">
                {shortcut.description}
              </span>
              <ShortcutKey keys={primaryKey} size="sm" />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default KeyboardShortcutsHelp;
