'use client';

import { useAdaptiveMode } from '@/context/AdaptiveModeContext';

interface AdaptiveModeToggleProps {
  /** Show text labels */
  showLabels?: boolean;
  /** Compact size for header/nav */
  compact?: boolean;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Toggle switch for Simple/Advanced UI mode
 *
 * Default is Simple mode. Toggle enables Advanced mode with
 * full configuration access, API explorer, and power features.
 */
export function AdaptiveModeToggle({
  showLabels = true,
  compact = false,
  className = '',
}: AdaptiveModeToggleProps) {
  const { toggleMode, isAdvanced, modeDescription } = useAdaptiveMode();

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {showLabels && (
        <span
          className={`
            font-theme-data transition-colors
            ${compact ? 'text-xs' : 'text-sm'}
            ${!isAdvanced ? 'text-[var(--accent)]' : 'text-text-muted'}
          `}
        >
          Simple
        </span>
      )}

      {/* Toggle switch */}
      <button
        onClick={toggleMode}
        role="switch"
        aria-checked={isAdvanced}
        aria-label={`Switch to ${isAdvanced ? 'simple' : 'advanced'} mode`}
        title={modeDescription}
        className={`
          relative inline-flex items-center
          ${compact ? 'h-5 w-10' : 'h-6 w-12'}
          rounded-full
          border border-[var(--accent)]/40
          transition-colors duration-200
          focus:outline-none focus:ring-2 focus:ring-acid-green/50
          ${isAdvanced ? 'bg-[var(--accent)]/20' : 'bg-surface'}
        `}
      >
        {/* Toggle knob */}
        <span
          className={`
            absolute
            ${compact ? 'h-3 w-3' : 'h-4 w-4'}
            rounded-full
            bg-[var(--accent)]
            shadow-lg shadow-acid-green/30
            transition-transform duration-200
            ${isAdvanced ? (compact ? 'translate-x-6' : 'translate-x-7') : 'translate-x-1'}
          `}
        />
      </button>

      {showLabels && (
        <span
          className={`
            font-theme-data transition-colors
            ${compact ? 'text-xs' : 'text-sm'}
            ${isAdvanced ? 'text-[var(--acid-cyan)]' : 'text-text-muted'}
          `}
        >
          Advanced
        </span>
      )}
    </div>
  );
}

/**
 * Compact mode indicator for nav headers
 *
 * Shows current mode as a badge that can be clicked to toggle
 */
export function AdaptiveModeBadge({ className = '' }: { className?: string }) {
  const { toggleMode, isAdvanced, modeLabel } = useAdaptiveMode();

  return (
    <button
      onClick={toggleMode}
      aria-label={`Toggle UI mode. Currently in ${modeLabel} mode.`}
      className={`
        px-2 py-0.5
        text-xs font-theme-data
        border rounded
        transition-colors
        ${
          isAdvanced
            ? 'border-[var(--acid-cyan)]/50 text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10'
            : 'border-[var(--accent)]/50 text-[var(--accent)] bg-[var(--accent)]/10'
        }
        hover:opacity-80
        ${className}
      `}
      title={`Currently in ${modeLabel} mode. Click to toggle.`}
    >
      {isAdvanced ? '[ADV]' : '[SMP]'}
    </button>
  );
}

/**
 * Full mode selector with descriptions
 *
 * For settings pages or initial setup
 */
export function AdaptiveModeCard({ className = '' }: { className?: string }) {
  const { setMode, isSimple, isAdvanced } = useAdaptiveMode();

  return (
    <div className={`border border-[var(--accent)]/30 bg-surface ${className}`}>
      <div className="border-b border-[var(--accent)]/20 px-4 py-3">
        <h3 className="text-text font-bold font-theme-data">UI Mode</h3>
        <p className="text-text-muted text-sm mt-1">Choose your interface complexity level</p>
      </div>

      <div className="p-4 space-y-3">
        {/* Simple Mode */}
        <button
          onClick={() => setMode('simple')}
          aria-pressed={isSimple}
          aria-label="Select simple mode"
          className={`
            w-full p-4 text-left border rounded
            transition-colors
            ${
              isSimple
                ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50'
            }
          `}
        >
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`font-theme-data font-bold ${isSimple ? 'text-[var(--accent)]' : 'text-text'}`}
            >
              Simple
            </span>
            {isSimple && <span className="text-xs text-[var(--accent)]">[ACTIVE]</span>}
          </div>
          <p className="text-sm text-text-muted">
            Streamlined interface with guided workflows, automatic agent selection, and summary
            results. Perfect for quick tasks and new users.
          </p>
        </button>

        {/* Advanced Mode */}
        <button
          onClick={() => setMode('advanced')}
          aria-pressed={isAdvanced}
          aria-label="Select advanced mode"
          className={`
            w-full p-4 text-left border rounded
            transition-colors
            ${
              isAdvanced
                ? 'border-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10'
                : 'border-[var(--accent)]/30 hover:border-[var(--accent)]/50'
            }
          `}
        >
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`font-theme-data font-bold ${isAdvanced ? 'text-[var(--acid-cyan)]' : 'text-text'}`}
            >
              Advanced
            </span>
            {isAdvanced && <span className="text-xs text-[var(--acid-cyan)]">[ACTIVE]</span>}
          </div>
          <p className="text-sm text-text-muted">
            Full control with all features: custom protocols, memory configuration, graph debates,
            workflow builder, API explorer, and admin tools.
          </p>
        </button>
      </div>
    </div>
  );
}
