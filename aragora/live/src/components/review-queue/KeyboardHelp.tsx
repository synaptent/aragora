'use client';

import { useEffect } from 'react';

export interface KeyboardHelpProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS: Array<{ keys: string; description: string }> = [
  { keys: 'j / k', description: 'Navigate down / up between cards' },
  { keys: '↵ / space', description: 'Toggle expand the selected card' },
  { keys: 'a', description: 'Approve the selected PR (confirms if brief disagrees)' },
  { keys: 'r', description: 'Request changes — opens reason prompt' },
  { keys: 'd', description: 'Defer the PR for 4 hours (local state only)' },
  { keys: 'o', description: 'Open the diff on github.com in a new tab' },
  { keys: '?', description: 'Toggle this help overlay' },
  { keys: 'Esc', description: 'Close this overlay or the active card' },
];

export function KeyboardHelp({ open, onClose }: KeyboardHelpProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-queue-help-title"
      data-testid="review-queue-keyboard-help"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <div
        className="max-w-md rounded-xl border p-6 text-sm shadow-xl"
        style={{
          borderColor: 'var(--border)',
          backgroundColor: 'var(--surface)',
          color: 'var(--text)',
          boxShadow: 'var(--shadow-floating)',
        }}
        onClick={(ev) => ev.stopPropagation()}
      >
        <div
          className="flex items-center justify-between border-b pb-3"
          style={{ borderColor: 'var(--border)' }}
        >
          <h2 id="review-queue-help-title" className="font-theme-data text-base">
            Keyboard shortcuts
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border px-3 py-1.5 text-xs font-theme-data uppercase tracking-wider hover:opacity-80"
            style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
          >
            close
          </button>
        </div>
        <table className="mt-4 w-full">
          <tbody>
            {SHORTCUTS.map((row) => (
              <tr key={row.keys} className="border-t" style={{ borderColor: 'var(--border)' }}>
                <td className="py-2 pr-4">
                  <kbd
                    className="rounded-md border font-theme-data"
                    style={{
                      padding: '0.25rem 0.625rem',
                      fontSize: '11px',
                      borderColor: 'var(--border)',
                      backgroundColor: 'var(--surface-elevated)',
                      color: 'var(--text)',
                    }}
                  >
                    {row.keys}
                  </kbd>
                </td>
                <td className="py-2" style={{ color: 'var(--text-muted)' }}>
                  {row.description}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
