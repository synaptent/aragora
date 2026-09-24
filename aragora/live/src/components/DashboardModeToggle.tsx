'use client';

import { DashboardMode } from '@/hooks/useDashboardPreferences';

interface DashboardModeToggleProps {
  mode: DashboardMode;
  onModeChange: (mode: DashboardMode) => void;
  compact?: boolean;
}

export function DashboardModeToggle({
  mode,
  onModeChange,
  compact = false,
}: DashboardModeToggleProps) {
  if (compact) {
    return (
      <button
        onClick={() => onModeChange(mode === 'focus' ? 'explorer' : 'focus')}
        className="px-2 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] hover:border-[var(--accent)] transition-colors"
        title={
          mode === 'focus'
            ? 'Switch to Explorer Mode (show all panels)'
            : 'Switch to Focus Mode (minimal panels)'
        }
        aria-label={
          mode === 'focus'
            ? 'Switch to Explorer Mode (show all panels)'
            : 'Switch to Focus Mode (minimal panels)'
        }
        aria-pressed={mode === 'focus'}
      >
        {mode === 'focus' ? '[FOCUS]' : '[EXPLORER]'}
      </button>
    );
  }

  return (
    <div
      className="flex items-center gap-1 bg-bg border border-[var(--accent)]/30 p-0.5 font-theme-data text-xs"
      role="group"
      aria-label="Dashboard mode selection"
    >
      <button
        onClick={() => onModeChange('focus')}
        className={`px-3 py-1.5 transition-colors ${
          mode === 'focus'
            ? 'bg-[var(--accent)] text-bg'
            : 'text-text-muted hover:text-[var(--accent)]'
        }`}
        title="Focus Mode: Show only essential panels for running debates"
        aria-label="Focus Mode: Show only essential panels for running debates"
        aria-pressed={mode === 'focus'}
      >
        [FOCUS]
      </button>
      <button
        onClick={() => onModeChange('explorer')}
        className={`px-3 py-1.5 transition-colors ${
          mode === 'explorer'
            ? 'bg-[var(--accent)] text-bg'
            : 'text-text-muted hover:text-[var(--accent)]'
        }`}
        title="Explorer Mode: Show all available panels and features"
        aria-label="Explorer Mode: Show all available panels and features"
        aria-pressed={mode === 'explorer'}
      >
        [EXPLORER]
      </button>
    </div>
  );
}

export function FocusModeIndicator({ onClick }: { onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 px-3 py-1.5 text-xs font-theme-data bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/20 transition-colors"
      title="You're in Focus Mode. Click to explore more features."
      aria-label="Focus Mode active. Click to explore more features."
    >
      <span
        className="w-2 h-2 bg-[var(--acid-cyan)] rounded-full animate-pulse"
        aria-hidden="true"
      />
      FOCUS MODE
    </button>
  );
}
