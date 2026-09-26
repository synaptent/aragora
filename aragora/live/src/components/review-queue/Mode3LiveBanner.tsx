'use client';

import { useEffect, useState } from 'react';

const DISMISS_KEY = 'aragora.mode3-banner-dismissed-v1';

/**
 * A dismissible banner announcing that Mode 3 on-demand brief generation
 * is live on the review queue. Shows once per browser until dismissed or
 * the user generates their first brief (handled elsewhere — this
 * component only handles the render + dismiss state).
 *
 * Layered on top of the queue so it doesn't disrupt keyboard flow.
 * Can be extended with a "tour" link or "open settings" once config UI
 * exists. For now: acknowledgement + get-started pointer.
 */
export function Mode3LiveBanner() {
  const [dismissed, setDismissed] = useState<boolean | null>(null);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(DISMISS_KEY);
      setDismissed(raw === '1');
    } catch {
      setDismissed(false);
    }
  }, []);

  if (dismissed === null || dismissed) {
    return null;
  }

  const handleDismiss = () => {
    try {
      window.localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      /* ignore — still dismiss for this session */
    }
    setDismissed(true);
  };

  return (
    <div
      role="status"
      className="mb-6 rounded-xl border flex items-start gap-3"
      style={{
        borderColor: 'var(--accent)',
        backgroundColor: 'var(--accent-glow)',
        padding: '1rem 1.25rem',
      }}
    >
      <span
        aria-hidden="true"
        className="font-theme-data"
        style={{ color: 'var(--accent)', fontSize: '18px', lineHeight: 1, marginTop: '2px' }}
      >
        ◆
      </span>
      <div className="flex-1">
        <div
          className="font-theme-data"
          style={{
            color: 'var(--accent)',
            fontSize: '12px',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            marginBottom: '4px',
          }}
        >
          Mode 3 — heterogeneous brief generation is live
        </div>
        <div style={{ color: 'var(--text)', fontSize: '14px', lineHeight: 1.5 }}>
          Click <span className="font-theme-data">Generate brief</span> on any PR to run the full
          panel debate — findings, critique, synthesis — and get a role-structured verdict with
          dissent preserved. First brief typically takes ~90s.
        </div>
        <div
          style={{
            color: 'var(--text-muted)',
            fontSize: '12px',
            marginTop: '6px',
            fontStyle: 'italic',
          }}
        >
          Requires <code className="font-theme-data">ARAGORA_PDB_BRIEF_GENERATION_ENABLED=1</code>{' '}
          on the backend. If the button is hidden, that flag is off.
        </div>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss announcement"
        className="font-theme-data transition-colors"
        style={{
          background: 'transparent',
          border: 'none',
          color: 'var(--text-muted)',
          cursor: 'pointer',
          fontSize: '16px',
          padding: '0 0.25rem',
          lineHeight: 1,
        }}
      >
        ×
      </button>
    </div>
  );
}
