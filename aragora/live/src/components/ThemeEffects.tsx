'use client';

import { useTheme } from '@/context/ThemeContext';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';

/**
 * Theme-aware background effects. Only renders scanlines and CRT vignette
 * in the dark theme. Warm and professional themes get clean backgrounds.
 */
export function ThemeEffects({ opacity = 0.02 }: { opacity?: number }) {
  const { theme } = useTheme();
  if (theme !== 'dark') return null;
  return (
    <>
      <Scanlines opacity={opacity} />
      <CRTVignette />
    </>
  );
}

/**
 * Returns the appropriate font class for the current theme.
 * Dark: monospace (terminal aesthetic)
 * Warm: serif display + sans body
 * Professional: clean sans-serif
 */
export function useThemeFont(): { display: string; body: string; mono: string } {
  const { theme } = useTheme();
  switch (theme) {
    case 'dark':
      return { display: 'font-theme-data', body: 'font-theme-data', mono: 'font-theme-data' };
    case 'warm':
      return {
        display: 'font-[var(--font-display)]',
        body: 'font-[var(--font-landing)]',
        mono: 'font-theme-data',
      };
    case 'professional':
    default:
      return {
        display: 'font-[var(--font-display)]',
        body: 'font-[var(--font-display)]',
        mono: 'font-theme-data',
      };
  }
}

/**
 * Returns theme-appropriate card styling.
 */
export function useThemeCard(): string {
  const { theme } = useTheme();
  switch (theme) {
    case 'dark':
      return 'border border-[var(--border)] bg-[var(--surface)]/50';
    case 'warm':
      return 'border border-[var(--border)] bg-[var(--surface)] rounded-[var(--radius-card)] shadow-[var(--shadow-card)]';
    case 'professional':
    default:
      return 'border border-[var(--border)] bg-[var(--surface)] rounded-lg shadow-[var(--shadow-card)]';
  }
}

/**
 * Returns theme-appropriate button styling for primary actions.
 */
export function useThemeButton(): { primary: string; secondary: string } {
  const { theme } = useTheme();
  switch (theme) {
    case 'dark':
      return {
        primary:
          'bg-[var(--accent)] text-[var(--bg)] font-theme-data font-bold hover:opacity-80 transition-colors',
        secondary:
          'border border-[var(--accent)]/30 text-[var(--accent)] font-theme-data hover:border-[var(--accent)] transition-colors',
      };
    case 'warm':
      return {
        primary:
          'bg-[var(--accent)] text-white font-[var(--font-landing)] font-semibold rounded-[var(--radius-button)] hover:opacity-90 transition-colors shadow-sm',
        secondary:
          'border border-[var(--accent)]/30 text-[var(--accent)] font-[var(--font-landing)] rounded-[var(--radius-button)] hover:border-[var(--accent)] transition-colors',
      };
    case 'professional':
    default:
      return {
        primary:
          'bg-[var(--accent)] text-white font-[var(--font-display)] font-medium rounded-lg hover:opacity-90 transition-colors shadow-sm',
        secondary:
          'border border-[var(--border)] text-[var(--text)] font-[var(--font-display)] rounded-lg hover:border-[var(--accent)] transition-colors',
      };
  }
}
