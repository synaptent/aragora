'use client';

export interface ToggleSwitchProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}

export function ToggleSwitch({
  label,
  description,
  checked,
  onChange,
  disabled = false,
}: ToggleSwitchProps) {
  return (
    <label
      className={`flex items-center justify-between ${
        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
      }`}
    >
      <div>
        <div className="font-theme-data text-sm text-text">{label}</div>
        {description && (
          <div className="font-theme-data text-xs text-text-muted">{description}</div>
        )}
      </div>
      <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        aria-disabled={disabled}
        onClick={onChange}
        disabled={disabled}
        className={`w-12 h-6 rounded-full transition-colors ${
          checked ? 'bg-[var(--accent)]' : 'bg-surface'
        } ${disabled ? 'cursor-not-allowed' : ''}`}
      >
        <div
          className={`w-5 h-5 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-6' : 'translate-x-0.5'
          }`}
        />
      </button>
    </label>
  );
}

export default ToggleSwitch;
