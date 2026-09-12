'use client';

import React, { forwardRef, HTMLAttributes } from 'react';

// =============================================================================
// Types
// =============================================================================

export type IconSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

export interface IconProps extends HTMLAttributes<HTMLSpanElement> {
  /** Icon name from the icon map */
  name: keyof typeof iconMap;
  /** Size of the icon */
  size?: IconSize;
  /** Custom class name */
  className?: string;
  /** Accessible label (for screen readers) */
  label?: string;
}

// =============================================================================
// Icon Map
// =============================================================================

/**
 * Icon map using Unicode/emoji characters.
 * This can be migrated to Lucide icons in the future by:
 * 1. npm install lucide-react
 * 2. Replace emoji values with Lucide components
 *
 * The API remains the same: <Icon name="home" />
 */
export const iconMap = {
  // Navigation
  home: '≡',
  dashboard: '≡',
  menu: '☰',
  settings: '*',
  admin: '⚙',
  about: 'i',

  // Actions
  add: '+',
  close: '×',
  check: '✓',
  search: '🔍',
  filter: '⚙',
  refresh: '↻',
  expand: '»',
  collapse: '«',
  edit: '✎',
  delete: '🗑',
  copy: '📋',
  download: '↓',
  upload: '↑',
  share: '↗',
  link: '🔗',

  // Debates & Agents
  debate: '⌘',
  agent: '&',
  knowledge: '?',
  workflow: '>',
  inbox: '!',
  analytics: '~',

  // Enterprise
  gauntlet: '⚡',
  compliance: '✓',
  controlPlane: '◎',
  receipts: '$',
  explainability: '💡',
  security: '🔒',

  // Browse
  gallery: '✦',
  leaderboard: '^',
  tournaments: '⊕',
  reviews: '<',

  // Tools
  documents: ']',
  connectors: '<',
  templates: '[',
  integrations: '∫',

  // Advanced
  genesis: '@',
  memory: '=',
  introspection: '⊙',

  // Status
  success: '✓',
  warning: '⚠',
  error: '✗',
  info: 'ℹ',
  loading: '◌',
  online: '●',
  offline: '○',

  // Arrows
  arrowUp: '↑',
  arrowDown: '↓',
  arrowLeft: '←',
  arrowRight: '→',
  chevronUp: '⌃',
  chevronDown: '⌄',
  chevronLeft: '‹',
  chevronRight: '›',

  // Misc
  star: '★',
  starOutline: '☆',
  heart: '♥',
  bell: '🔔',
  user: '👤',
  users: '👥',
  lock: '🔒',
  unlock: '🔓',
  key: '🔑',
  calendar: '📅',
  clock: '🕐',
  lightning: '⚡',
  fire: '🔥',
  sparkle: '✨',
  terminal: '>_',
  code: '</>',
  eye: '👁',
  eyeOff: '🚫',
} as const;

export type IconName = keyof typeof iconMap;

// =============================================================================
// Styles
// =============================================================================

const sizeClasses: Record<IconSize, string> = {
  xs: 'text-xs w-3 h-3',
  sm: 'text-sm w-4 h-4',
  md: 'text-base w-5 h-5',
  lg: 'text-lg w-6 h-6',
  xl: 'text-xl w-8 h-8',
};

// =============================================================================
// Component
// =============================================================================

export const Icon = forwardRef<HTMLSpanElement, IconProps>(
  ({ name, size = 'md', className = '', label, ...props }, ref) => {
    const iconChar = iconMap[name];

    return (
      <span
        ref={ref}
        role={label ? 'img' : 'presentation'}
        aria-label={label}
        aria-hidden={!label}
        className={`
          inline-flex items-center justify-center
          font-theme-data leading-none
          ${sizeClasses[size]}
          ${className}
        `}
        {...props}
      >
        {iconChar}
      </span>
    );
  },
);

Icon.displayName = 'Icon';

// =============================================================================
// Helper Components
// =============================================================================

/**
 * Icon with text label
 */
export interface IconWithLabelProps extends IconProps {
  children: React.ReactNode;
  /** Label position */
  labelPosition?: 'left' | 'right';
}

export function IconWithLabel({
  children,
  labelPosition = 'right',
  className = '',
  ...iconProps
}: IconWithLabelProps) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      {labelPosition === 'left' && <span>{children}</span>}
      <Icon {...iconProps} />
      {labelPosition === 'right' && <span>{children}</span>}
    </span>
  );
}

/**
 * Animated loading icon
 */
export function LoadingIcon({
  size = 'md',
  className = '',
}: {
  size?: IconSize;
  className?: string;
}) {
  return (
    <span
      className={`
        inline-flex items-center justify-center
        animate-spin
        ${sizeClasses[size]}
        ${className}
      `}
      role="status"
      aria-label="Loading"
    >
      <svg
        className="w-full h-full"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
    </span>
  );
}

/**
 * Status indicator dot
 */
export function StatusIndicator({
  status,
  size = 'sm',
  className = '',
  label,
}: {
  status: 'online' | 'offline' | 'warning' | 'error';
  size?: IconSize;
  className?: string;
  label?: string;
}) {
  const statusColors: Record<typeof status, string> = {
    online: 'bg-green-500',
    offline: 'bg-gray-500',
    warning: 'bg-yellow-500',
    error: 'bg-red-500',
  };

  const dotSizes: Record<IconSize, string> = {
    xs: 'w-1.5 h-1.5',
    sm: 'w-2 h-2',
    md: 'w-2.5 h-2.5',
    lg: 'w-3 h-3',
    xl: 'w-4 h-4',
  };

  return (
    <span
      className={`
        inline-block rounded-full
        ${dotSizes[size]}
        ${statusColors[status]}
        ${status === 'online' ? 'animate-pulse' : ''}
        ${className}
      `}
      role="status"
      aria-label={label || status}
    />
  );
}

export default Icon;
