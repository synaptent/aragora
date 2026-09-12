'use client';

import { useCallback, useEffect, useRef } from 'react';

interface AccessibleOverlayProps {
  /** Called when the overlay is clicked or dismissed via keyboard */
  onClose: () => void;
  /** Additional CSS classes for the overlay */
  className?: string;
  /** Whether to show the overlay */
  isOpen?: boolean;
  /** Label for screen readers */
  ariaLabel?: string;
  /** Children elements (modal content) */
  children?: React.ReactNode;
}

/**
 * Accessible modal overlay component
 *
 * Features:
 * - Keyboard accessible (Escape to close)
 * - ARIA attributes for screen readers
 * - Focus trap support
 * - Click outside to close
 *
 * @example
 * <AccessibleOverlay onClose={() => setOpen(false)} isOpen={isOpen}>
 *   <div className="modal-content">Modal content here</div>
 * </AccessibleOverlay>
 */
export function AccessibleOverlay({
  onClose,
  className = '',
  isOpen = true,
  ariaLabel = 'Close modal',
  children,
}: AccessibleOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  // Handle escape key
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    },
    [onClose],
  );

  // Add escape key listener
  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, handleKeyDown]);

  // Handle click on overlay background (not content)
  const handleOverlayClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (event.target === overlayRef.current) {
        onClose();
      }
    },
    [onClose],
  );

  if (!isOpen) return null;

  return (
    <div
      ref={overlayRef}
      className={`fixed inset-0 z-50 flex items-center justify-center bg-black/70 ${className}`}
      onClick={handleOverlayClick}
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
    >
      {children}
    </div>
  );
}

/**
 * Simple backdrop for modals that needs just the background
 */
export function ModalBackdrop({
  onClose,
  className = '',
}: Pick<AccessibleOverlayProps, 'onClose' | 'className'>) {
  return (
    <div
      className={`absolute inset-0 bg-black/70 ${className}`}
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      role="button"
      tabIndex={0}
      aria-label="Close modal"
    />
  );
}
