/**
 * VisibilitySelector Component
 *
 * A dropdown selector for setting the visibility level of knowledge items.
 * Supports: private, workspace, organization, public, system
 */

import React, { useState, useCallback } from 'react';

export type VisibilityLevel = 'private' | 'workspace' | 'organization' | 'public' | 'system';

export interface VisibilitySelectorProps {
  /** Current visibility level */
  value: VisibilityLevel;
  /** Callback when visibility changes */
  onChange: (visibility: VisibilityLevel) => void;
  /** Whether the selector is disabled */
  disabled?: boolean;
  /** Whether to show the system visibility option (admin only) */
  showSystem?: boolean;
  /** Optional class name */
  className?: string;
}

interface VisibilityOption {
  value: VisibilityLevel;
  label: string;
  description: string;
  icon: string;
}

const VISIBILITY_OPTIONS: VisibilityOption[] = [
  {
    value: 'private',
    label: 'Private',
    description: 'Only you and explicitly granted users',
    icon: '🔒',
  },
  {
    value: 'workspace',
    label: 'Workspace',
    description: 'All members of this workspace',
    icon: '👥',
  },
  {
    value: 'organization',
    label: 'Organization',
    description: 'All members of the organization',
    icon: '🏢',
  },
  { value: 'public', label: 'Public', description: 'Anyone with the link', icon: '🌐' },
  {
    value: 'system',
    label: 'System',
    description: 'Global verified facts (admin only)',
    icon: '⚙️',
  },
];

export const VisibilitySelector: React.FC<VisibilitySelectorProps> = ({
  value,
  onChange,
  disabled = false,
  showSystem = false,
  className = '',
}) => {
  const [isOpen, setIsOpen] = useState(false);

  const options = showSystem
    ? VISIBILITY_OPTIONS
    : VISIBILITY_OPTIONS.filter((opt) => opt.value !== 'system');

  const selectedOption = options.find((opt) => opt.value === value) || options[1];

  const handleSelect = useCallback(
    (visibility: VisibilityLevel) => {
      onChange(visibility);
      setIsOpen(false);
    },
    [onChange],
  );

  return (
    <div className={`relative inline-block ${className}`}>
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={`
          flex items-center gap-2 px-3 py-2 rounded-md border
          ${disabled ? 'bg-gray-100 cursor-not-allowed' : 'bg-white hover:bg-gray-50 cursor-pointer'}
          border-gray-300 text-sm font-medium text-gray-700
          focus:outline-none focus:ring-2 focus:ring-blue-500
        `}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span>{selectedOption.icon}</span>
        <span>{selectedOption.label}</span>
        <svg
          className={`w-4 h-4 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} aria-hidden="true" />

          {/* Dropdown */}
          <ul
            className="absolute z-20 mt-1 w-64 bg-white border border-gray-200 rounded-md shadow-lg py-1"
            role="listbox"
            aria-label="Visibility options"
          >
            {options.map((option) => (
              <li
                key={option.value}
                role="option"
                aria-selected={option.value === value}
                className={`
                  px-3 py-2 cursor-pointer hover:bg-gray-50
                  ${option.value === value ? 'bg-blue-50' : ''}
                `}
                onClick={() => handleSelect(option.value)}
              >
                <div className="flex items-center gap-2">
                  <span>{option.icon}</span>
                  <div>
                    <div className="text-sm font-medium text-gray-900">{option.label}</div>
                    <div className="text-xs text-gray-500">{option.description}</div>
                  </div>
                  {option.value === value && (
                    <svg
                      className="w-4 h-4 ml-auto text-blue-600"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
};

export default VisibilitySelector;
