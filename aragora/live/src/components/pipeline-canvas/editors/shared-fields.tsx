'use client';

import { memo, useCallback } from 'react';

/* -------------------------------------------------------------------------- */
/*  Prop interfaces                                                           */
/* -------------------------------------------------------------------------- */

export interface InputFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: 'text' | 'number' | 'textarea';
}

export interface SelectFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}

export interface MultiSelectProps {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  options: Array<{ value: string; label: string }>;
}

export interface SliderFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  formatLabel?: (value: number) => string;
}

export interface CheckboxFieldProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  description?: string;
}

/* -------------------------------------------------------------------------- */
/*  Shared Tailwind fragments                                                 */
/* -------------------------------------------------------------------------- */

const LABEL_CLS = 'block text-xs text-text-muted mb-1';
const INPUT_CLS =
  'w-full bg-bg border border-border rounded px-2 py-1.5 text-sm text-text font-theme-data focus:outline-none focus:ring-1 focus:ring-acid-green';

/* -------------------------------------------------------------------------- */
/*  InputField                                                                */
/* -------------------------------------------------------------------------- */

export const InputField = memo(function InputField({
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
}: InputFieldProps) {
  return (
    <div className="mb-3">
      <label className={LABEL_CLS}>{label}</label>
      {type === 'textarea' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className={`${INPUT_CLS} resize-none`}
        />
      ) : (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={INPUT_CLS}
        />
      )}
    </div>
  );
});

/* -------------------------------------------------------------------------- */
/*  SelectField                                                               */
/* -------------------------------------------------------------------------- */

export const SelectField = memo(function SelectField({
  label,
  value,
  onChange,
  options,
}: SelectFieldProps) {
  return (
    <div className="mb-3">
      <label className={LABEL_CLS}>{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={INPUT_CLS}>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
});

/* -------------------------------------------------------------------------- */
/*  MultiSelect                                                               */
/* -------------------------------------------------------------------------- */

export const MultiSelect = memo(function MultiSelect({
  label,
  values,
  onChange,
  options,
}: MultiSelectProps) {
  const toggle = useCallback(
    (optValue: string) => {
      if (values.includes(optValue)) {
        onChange(values.filter((v) => v !== optValue));
      } else {
        onChange([...values, optValue]);
      }
    },
    [values, onChange],
  );

  return (
    <div className="mb-3">
      <label className={LABEL_CLS}>{label}</label>
      <div className="flex flex-col gap-1 p-2 bg-bg border border-border rounded max-h-40 overflow-y-auto">
        {options.map((opt) => (
          <label
            key={opt.value}
            className="flex items-center gap-2 text-sm font-theme-data cursor-pointer"
          >
            <input
              type="checkbox"
              checked={values.includes(opt.value)}
              onChange={() => toggle(opt.value)}
              className="accent-emerald-500"
            />
            <span className="text-text">{opt.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
});

/* -------------------------------------------------------------------------- */
/*  SliderField                                                               */
/* -------------------------------------------------------------------------- */

export const SliderField = memo(function SliderField({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  formatLabel,
}: SliderFieldProps) {
  const display = formatLabel ? formatLabel(value) : `${value}`;

  return (
    <div className="mb-3">
      <label className={LABEL_CLS}>
        {label}: {display}
      </label>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-emerald-500"
      />
    </div>
  );
});

/* -------------------------------------------------------------------------- */
/*  CheckboxField                                                             */
/* -------------------------------------------------------------------------- */

export const CheckboxField = memo(function CheckboxField({
  label,
  checked,
  onChange,
  description,
}: CheckboxFieldProps) {
  return (
    <div className="mb-3">
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="accent-emerald-500"
        />
        <span className="text-sm text-text">{label}</span>
      </label>
      {description && <p className="text-xs text-text-muted mt-0.5 ml-6">{description}</p>}
    </div>
  );
});
