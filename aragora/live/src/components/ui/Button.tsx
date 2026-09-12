'use client';

import React, { forwardRef, ButtonHTMLAttributes, ReactNode } from 'react';

// =============================================================================
// Types
// =============================================================================

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual style variant */
  variant?: ButtonVariant;
  /** Size of the button */
  size?: ButtonSize;
  /** Show loading spinner */
  loading?: boolean;
  /** Icon to show before text */
  leftIcon?: ReactNode;
  /** Icon to show after text */
  rightIcon?: ReactNode;
  /** Make button full width */
  fullWidth?: boolean;
  /** Children content */
  children?: ReactNode;
}

// =============================================================================
// Styles
// =============================================================================

const baseStyles = `
  inline-flex items-center justify-center gap-2
  font-medium rounded-lg transition-all duration-200
  focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-[var(--bg)]
  disabled:opacity-50 disabled:cursor-not-allowed
`;

const variantStyles: Record<ButtonVariant, string> = {
  primary: `
    bg-[var(--accent)] text-[var(--bg)]
    hover:bg-[var(--accent)]/90 hover:shadow-[0_0_20px_var(--accent-glow)]
    focus:ring-[var(--accent)]
    active:scale-[0.98]
  `,
  secondary: `
    bg-[var(--surface-elevated)] text-[var(--text)]
    border border-[var(--border)]
    hover:bg-[var(--surface-elevated)]/80 hover:border-[var(--accent)]/30
    focus:ring-[var(--accent)]/50
    active:scale-[0.98]
  `,
  ghost: `
    bg-transparent text-[var(--text-muted)]
    hover:bg-[var(--surface-elevated)] hover:text-[var(--text)]
    focus:ring-[var(--accent)]/30
    active:scale-[0.98]
  `,
  danger: `
    bg-red-500/10 text-red-400
    border border-red-500/30
    hover:bg-red-500/20 hover:border-red-500/50
    focus:ring-red-500/50
    active:scale-[0.98]
  `,
  outline: `
    bg-transparent text-[var(--accent)]
    border border-[var(--accent)]/50
    hover:bg-[var(--accent)]/10 hover:border-[var(--accent)]
    focus:ring-[var(--accent)]/50
    active:scale-[0.98]
  `,
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-xs min-h-[32px]',
  md: 'px-4 py-2 text-sm min-h-[40px]',
  lg: 'px-6 py-3 text-base min-h-[48px]',
};

// =============================================================================
// Loading Spinner
// =============================================================================

function LoadingSpinner({ size }: { size: ButtonSize }) {
  const spinnerSize = size === 'sm' ? 'w-3 h-3' : size === 'lg' ? 'w-5 h-5' : 'w-4 h-4';

  return (
    <svg
      className={`animate-spin ${spinnerSize}`}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

// =============================================================================
// Component
// =============================================================================

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      leftIcon,
      rightIcon,
      fullWidth = false,
      disabled,
      className = '',
      children,
      ...props
    },
    ref,
  ) => {
    const isDisabled = disabled || loading;

    return (
      <button
        ref={ref}
        disabled={isDisabled}
        className={`
          ${baseStyles}
          ${variantStyles[variant]}
          ${sizeStyles[size]}
          ${fullWidth ? 'w-full' : ''}
          ${className}
        `}
        {...props}
      >
        {loading ? (
          <LoadingSpinner size={size} />
        ) : leftIcon ? (
          <span className="flex-shrink-0" aria-hidden="true">
            {leftIcon}
          </span>
        ) : null}

        {children && <span>{children}</span>}

        {rightIcon && !loading && (
          <span className="flex-shrink-0" aria-hidden="true">
            {rightIcon}
          </span>
        )}
      </button>
    );
  },
);

Button.displayName = 'Button';

// =============================================================================
// Icon Button Variant
// =============================================================================

export interface IconButtonProps extends Omit<ButtonProps, 'leftIcon' | 'rightIcon' | 'children'> {
  /** Icon to display */
  icon: ReactNode;
  /** Accessible label (required for icon-only buttons) */
  'aria-label': string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ icon, size = 'md', className = '', ...props }, ref) => {
    const iconSizeStyles: Record<ButtonSize, string> = {
      sm: 'w-8 h-8 min-h-[32px]',
      md: 'w-10 h-10 min-h-[40px]',
      lg: 'w-12 h-12 min-h-[48px]',
    };

    return (
      <Button
        ref={ref}
        size={size}
        className={`${iconSizeStyles[size]} !p-0 ${className}`}
        {...props}
      >
        {icon}
      </Button>
    );
  },
);

IconButton.displayName = 'IconButton';

// =============================================================================
// Button Group
// =============================================================================

export interface ButtonGroupProps {
  children: ReactNode;
  /** Attach buttons together */
  attached?: boolean;
  /** Direction of group */
  direction?: 'horizontal' | 'vertical';
  className?: string;
}

export function ButtonGroup({
  children,
  attached = false,
  direction = 'horizontal',
  className = '',
}: ButtonGroupProps) {
  const directionStyles = direction === 'horizontal' ? 'flex-row' : 'flex-col';
  const attachedStyles = attached
    ? direction === 'horizontal'
      ? '[&>*:not(:first-child)]:rounded-l-none [&>*:not(:last-child)]:rounded-r-none [&>*:not(:first-child)]:border-l-0'
      : '[&>*:not(:first-child)]:rounded-t-none [&>*:not(:last-child)]:rounded-b-none [&>*:not(:first-child)]:border-t-0'
    : 'gap-2';

  return (
    <div className={`inline-flex ${directionStyles} ${attachedStyles} ${className}`} role="group">
      {children}
    </div>
  );
}

export default Button;
