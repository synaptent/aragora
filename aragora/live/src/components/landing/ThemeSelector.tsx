'use client';

import { useTheme, type Theme } from '@/context/ThemeContext';

interface ThemeOption {
  value: Theme;
  label: string;
  icon: React.ReactNode;
}

const SunIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="8" cy="8" r="3" />
    <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.17 3.17l1.06 1.06M11.77 11.77l1.06 1.06M3.17 12.83l1.06-1.06M11.77 4.23l1.06-1.06" />
  </svg>
);

const MoonIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M13.5 8.5a5.5 5.5 0 01-7.78 1.22A5.5 5.5 0 018 2.5a4.5 4.5 0 005.5 6z" />
  </svg>
);

const SaturnIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="8" cy="8" r="3.5" />
    <ellipse cx="8" cy="8" rx="7" ry="2.5" transform="rotate(-30 8 8)" />
  </svg>
);

const THEME_OPTIONS: ThemeOption[] = [
  { value: 'warm', label: 'Warm', icon: <SunIcon /> },
  { value: 'dark', label: 'Dark', icon: <MoonIcon /> },
  { value: 'professional', label: 'Pro', icon: <SaturnIcon /> },
];

export function ThemeSelector() {
  const { theme, setTheme, isInitialized } = useTheme();

  if (!isInitialized) {
    return (
      <div
        className="flex items-center gap-1 p-1.5"
        style={{
          backgroundColor: 'var(--surface)',
          borderRadius: 'var(--radius-card)',
          border: '1px solid var(--border)',
        }}
      >
        <span
          className="w-20 h-7 animate-pulse"
          style={{ backgroundColor: 'var(--border)', borderRadius: 'var(--radius-card)' }}
        />
      </div>
    );
  }

  return (
    <div
      className="flex items-center gap-1 p-1.5"
      role="radiogroup"
      aria-label="Theme selection"
      style={{
        backgroundColor: 'var(--surface)',
        borderRadius: 'var(--radius-card)',
        border: '1px solid var(--border)',
      }}
    >
      {THEME_OPTIONS.map((option) => {
        const isActive = theme === option.value;
        return (
          <button
            key={option.value}
            role="radio"
            aria-checked={isActive}
            aria-label={`${option.label} theme`}
            onClick={() => setTheme(option.value)}
            className="flex items-center gap-1.5 px-3 py-2 text-xs transition-colors cursor-pointer"
            style={{
              fontFamily: 'var(--font-landing)',
              borderRadius: 'var(--radius-card)',
              backgroundColor: isActive ? 'var(--accent)' : 'transparent',
              color: isActive ? 'var(--bg)' : 'var(--text-muted)',
            }}
          >
            {option.icon}
            <span className="hidden sm:inline">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
