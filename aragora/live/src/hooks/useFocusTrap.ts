'use client';

import { useEffect, useRef, useCallback } from 'react';

const FOCUSABLE_SELECTORS = [
  'button:not([disabled])',
  'a[href]',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

interface UseFocusTrapOptions {
  isActive: boolean;
  onEscape?: () => void;
  returnFocusOnDeactivate?: boolean;
}

/**
 * Focus trap hook for modal dialogs.
 * Traps keyboard focus within the container and handles Escape key.
 */
export function useFocusTrap<T extends HTMLElement = HTMLDivElement>({
  isActive,
  onEscape,
  returnFocusOnDeactivate = true,
}: UseFocusTrapOptions) {
  const containerRef = useRef<T>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  const getFocusableElements = useCallback(() => {
    if (!containerRef.current) return [];
    return Array.from(
      containerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS),
    ).filter((el) => el.offsetParent !== null); // Filter out hidden elements
  }, []);

  // Store the previously focused element when trap activates
  useEffect(() => {
    if (isActive) {
      previouslyFocusedRef.current = document.activeElement as HTMLElement;
    }
  }, [isActive]);

  // Focus first focusable element when trap activates
  useEffect(() => {
    if (!isActive || !containerRef.current) return;

    // Small delay to ensure modal is rendered
    const timeoutId = setTimeout(() => {
      const focusableElements = getFocusableElements();
      if (focusableElements.length > 0) {
        focusableElements[0].focus();
      } else {
        // If no focusable elements, focus the container itself
        containerRef.current?.focus();
      }
    }, 0);

    return () => clearTimeout(timeoutId);
  }, [isActive, getFocusableElements]);

  // Restore focus when trap deactivates
  useEffect(() => {
    if (!isActive && returnFocusOnDeactivate && previouslyFocusedRef.current) {
      previouslyFocusedRef.current.focus();
      previouslyFocusedRef.current = null;
    }
  }, [isActive, returnFocusOnDeactivate]);

  // Handle keyboard navigation
  useEffect(() => {
    if (!isActive) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && onEscape) {
        event.preventDefault();
        onEscape();
        return;
      }

      if (event.key !== 'Tab') return;

      const focusableElements = getFocusableElements();
      if (focusableElements.length === 0) return;

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      // Shift+Tab from first element -> go to last element
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
        return;
      }

      // Tab from last element -> go to first element
      if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isActive, getFocusableElements, onEscape]);

  return containerRef;
}

export default useFocusTrap;
