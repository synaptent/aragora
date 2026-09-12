'use client';

import { useTheme, type Theme } from '@/context/ThemeContext';

const THEME_OPTIONS: Array<{ value: Theme; label: string; glyph: string; title: string }> = [
  {
    value: 'warm',
    label: 'Warm',
    glyph: '☀',
    title: 'Warm theme — humanistic cream + forest green',
  },
  { value: 'dark', label: 'Dark', glyph: '◐', title: 'Dark theme — demoscene black + acid green' },
  {
    value: 'professional',
    label: 'Pro',
    glyph: '◆',
    title: 'Professional theme — muted, enterprise-ready',
  },
];

export function ThemeToggle() {
  const { theme, setTheme, isInitialized } = useTheme();

  if (!isInitialized) {
    return (
      <div
        aria-label="Theme selector"
        className="inline-flex"
        style={{ width: '120px', height: '28px' }}
      />
    );
  }

  return (
    <div
      role="radiogroup"
      aria-label="Theme selector"
      className="inline-flex items-center rounded-md border"
      style={{
        borderColor: 'var(--border)',
        backgroundColor: 'var(--surface-elevated)',
        padding: '2px',
        gap: '2px',
      }}
    >
      {THEME_OPTIONS.map((opt) => {
        const active = theme === opt.value;
        return (
          <button
            key={opt.value}
            role="radio"
            aria-checked={active}
            title={opt.title}
            onClick={() => setTheme(opt.value)}
            className="font-theme-data transition-colors"
            style={{
              padding: '2px 8px',
              fontSize: '11px',
              borderRadius: '4px',
              backgroundColor: active ? 'var(--accent-glow)' : 'transparent',
              color: active ? 'var(--accent)' : 'var(--text-muted)',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            <span aria-hidden="true" style={{ marginRight: '4px' }}>
              {opt.glyph}
            </span>
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Extended theme toggle with system preference option.
 * Shows three-state: dark, light, system (auto).
 */
export function ThemeSelector() {
  const { preference, setTheme, isInitialized } = useTheme();

  if (!isInitialized) {
    return (
      <div className="flex gap-1 p-1 bg-surface rounded">
        <span className="w-20 h-8 bg-surface-elevated rounded animate-pulse" />
      </div>
    );
  }

  return (
    <div
      className="flex gap-1 p-1 bg-surface rounded"
      role="radiogroup"
      aria-label="Theme selection"
    >
      <button
        role="radio"
        aria-checked={preference === 'dark'}
        onClick={() => setTheme('dark')}
        className={`px-3 py-1.5 text-xs font-theme-data rounded transition-colors ${
          preference === 'dark'
            ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
            : 'text-text-muted hover:text-text'
        }`}
      >
        Dark
      </button>
      <button
        role="radio"
        aria-checked={preference === 'light'}
        onClick={() => setTheme('light')}
        className={`px-3 py-1.5 text-xs font-theme-data rounded transition-colors ${
          preference === 'light'
            ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
            : 'text-text-muted hover:text-text'
        }`}
      >
        Light
      </button>
      <button
        role="radio"
        aria-checked={preference === 'system'}
        onClick={() => setTheme('system')}
        className={`px-3 py-1.5 text-xs font-theme-data rounded transition-colors ${
          preference === 'system'
            ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
            : 'text-text-muted hover:text-text'
        }`}
      >
        Auto
      </button>
    </div>
  );
}
