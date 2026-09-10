/**
 * MobileMenu - Slide-in mobile navigation menu.
 *
 * Features:
 * - Full-screen overlay with slide animation
 * - Focus trap when open
 * - Edge swipe to open/close
 * - Keyboard accessible (Escape to close)
 * - Safe area support
 * - Nested menu support
 */

'use client';

import React, {
  useEffect,
  useState,
  useCallback,
  ReactNode,
  createContext,
  useContext,
} from 'react';
import { cn } from '@/lib/utils';
import { useFocusTrap } from '@/hooks/useFocusTrap';
import { useEdgeSwipe } from '@/hooks/useSwipeGesture';
import { usePrefersReducedMotion, useIsMobile } from '@/hooks/useMediaQuery';

// =============================================================================
// Context
// =============================================================================

interface MobileMenuContextValue {
  isOpen: boolean;
  openMenu: () => void;
  closeMenu: () => void;
  toggleMenu: () => void;
}

const MobileMenuContext = createContext<MobileMenuContextValue | null>(null);

export function useMobileMenu() {
  const context = useContext(MobileMenuContext);
  if (!context) {
    throw new Error('useMobileMenu must be used within MobileMenuProvider');
  }
  return context;
}

// =============================================================================
// Provider
// =============================================================================

interface MobileMenuProviderProps {
  children: ReactNode;
  /** Enable edge swipe to open */
  edgeSwipeEnabled?: boolean;
}

export function MobileMenuProvider({ children, edgeSwipeEnabled = true }: MobileMenuProviderProps) {
  const [isOpen, setIsOpen] = useState(false);

  const openMenu = useCallback(() => setIsOpen(true), []);
  const closeMenu = useCallback(() => setIsOpen(false), []);
  const toggleMenu = useCallback(() => setIsOpen((prev) => !prev), []);

  // Edge swipe to open
  useEdgeSwipe({ edge: 'left', onSwipe: openMenu, enabled: edgeSwipeEnabled && !isOpen });

  return (
    <MobileMenuContext.Provider value={{ isOpen, openMenu, closeMenu, toggleMenu }}>
      {children}
    </MobileMenuContext.Provider>
  );
}

// =============================================================================
// Types
// =============================================================================

export interface MenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  href?: string;
  onClick?: () => void;
  children?: MenuItem[];
  badge?: string | number;
  disabled?: boolean;
}

interface MobileMenuProps {
  /** Menu items */
  items: MenuItem[];
  /** Header content (logo, user info, etc) */
  header?: ReactNode;
  /** Footer content */
  footer?: ReactNode;
  /** Custom class name */
  className?: string;
  /** Position of the menu */
  position?: 'left' | 'right';
  /** Width of the menu */
  width?: 'sm' | 'md' | 'lg' | 'full';
}

// =============================================================================
// Styles
// =============================================================================

const widthClasses = { sm: 'w-64', md: 'w-80', lg: 'w-96', full: 'w-full' };

// =============================================================================
// Haptic feedback
// =============================================================================

function triggerHaptic() {
  if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    navigator.vibrate(10);
  }
}

// =============================================================================
// Components
// =============================================================================

export function MobileMenu({
  items,
  header,
  footer,
  className,
  position = 'left',
  width = 'md',
}: MobileMenuProps) {
  const { isOpen, closeMenu } = useMobileMenu();
  const prefersReducedMotion = usePrefersReducedMotion();
  const isMobile = useIsMobile();
  const [mounted, setMounted] = useState(false);

  // Focus trap (handles escape key automatically)
  const focusTrapRef = useFocusTrap<HTMLDivElement>({ isActive: isOpen, onEscape: closeMenu });

  // Mount animation
  useEffect(() => {
    setMounted(true);
  }, []);

  // Lock body scroll when open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }

    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  // Edge swipe to close
  useEdgeSwipe({
    edge: position === 'left' ? 'right' : 'left',
    onSwipe: closeMenu,
    enabled: isOpen,
    edgeWidth: 40,
  });

  if (!mounted || (!isMobile && !isOpen)) return null;

  const slideClass =
    position === 'left'
      ? isOpen
        ? 'translate-x-0'
        : '-translate-x-full'
      : isOpen
        ? 'translate-x-0'
        : 'translate-x-full';

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          'fixed inset-0 z-40 bg-black/50',
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none',
          !prefersReducedMotion && 'transition-opacity duration-300',
        )}
        onClick={closeMenu}
        aria-hidden="true"
      />

      {/* Menu panel */}
      <div
        ref={focusTrapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
        className={cn(
          'fixed top-0 bottom-0 z-50',
          position === 'left' ? 'left-0' : 'right-0',
          widthClasses[width],
          'bg-background shadow-xl',
          'flex flex-col',
          // Safe area padding
          'pt-[env(safe-area-inset-top,0px)]',
          'pb-[env(safe-area-inset-bottom,0px)]',
          // Animation
          !prefersReducedMotion && 'transition-transform duration-300 ease-out',
          slideClass,
          className,
        )}
      >
        {/* Header */}
        {header && <div className="flex-shrink-0 px-4 py-4 border-b">{header}</div>}

        {/* Menu items */}
        <nav className="flex-1 overflow-y-auto py-4" role="navigation">
          <ul className="space-y-1">
            {items.map((item) => (
              <MenuItemComponent key={item.id} item={item} onClose={closeMenu} />
            ))}
          </ul>
        </nav>

        {/* Footer */}
        {footer && <div className="flex-shrink-0 px-4 py-4 border-t">{footer}</div>}
      </div>
    </>
  );
}

// =============================================================================
// Menu Item Component
// =============================================================================

interface MenuItemComponentProps {
  item: MenuItem;
  onClose: () => void;
  depth?: number;
}

function MenuItemComponent({ item, onClose, depth = 0 }: MenuItemComponentProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const hasChildren = item.children && item.children.length > 0;

  const handleClick = () => {
    if (item.disabled) return;

    triggerHaptic();

    if (hasChildren) {
      setIsExpanded(!isExpanded);
    } else {
      item.onClick?.();
      onClose();
    }
  };

  const Component = item.href ? 'a' : 'button';

  return (
    <li>
      <Component
        href={item.href}
        onClick={handleClick}
        disabled={item.disabled}
        className={cn(
          'w-full flex items-center gap-3 px-4 py-3',
          'text-left',
          'transition-colors duration-150',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary',
          item.disabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-muted active:bg-muted/80',
          depth > 0 && 'pl-8',
        )}
        style={{ paddingLeft: depth > 0 ? `${(depth + 1) * 16}px` : undefined }}
        aria-expanded={hasChildren ? isExpanded : undefined}
      >
        {/* Icon */}
        {item.icon && (
          <span className="flex-shrink-0 w-5 h-5 text-muted-foreground">{item.icon}</span>
        )}

        {/* Label */}
        <span className="flex-1 font-medium">{item.label}</span>

        {/* Badge */}
        {item.badge !== undefined && (
          <span className="flex-shrink-0 px-2 py-0.5 text-xs font-medium rounded-full bg-primary/10 text-primary">
            {item.badge}
          </span>
        )}

        {/* Expand indicator */}
        {hasChildren && (
          <svg
            className={cn(
              'w-4 h-4 text-muted-foreground transition-transform',
              isExpanded && 'rotate-90',
            )}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        )}
      </Component>

      {/* Children */}
      {hasChildren && isExpanded && (
        <ul className="bg-muted/30">
          {item.children!.map((child) => (
            <MenuItemComponent key={child.id} item={child} onClose={onClose} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

// =============================================================================
// Hamburger Button
// =============================================================================

interface HamburgerButtonProps {
  className?: string;
  'aria-label'?: string;
}

export function HamburgerButton({
  className,
  'aria-label': ariaLabel = 'Toggle menu',
}: HamburgerButtonProps) {
  const { isOpen, toggleMenu } = useMobileMenu();

  return (
    <button
      onClick={toggleMenu}
      className={cn(
        'relative w-10 h-10 flex items-center justify-center',
        'rounded-lg',
        'hover:bg-muted active:bg-muted/80',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        className,
      )}
      aria-label={ariaLabel}
      aria-expanded={isOpen}
    >
      <span className="sr-only">{isOpen ? 'Close menu' : 'Open menu'}</span>
      <div className="relative w-5 h-4">
        <span
          className={cn(
            'absolute left-0 right-0 h-0.5 bg-current rounded-full',
            'transition-all duration-300',
            isOpen ? 'top-1/2 -translate-y-1/2 rotate-45' : 'top-0',
          )}
        />
        <span
          className={cn(
            'absolute left-0 right-0 h-0.5 bg-current rounded-full',
            'top-1/2 -translate-y-1/2',
            'transition-opacity duration-300',
            isOpen && 'opacity-0',
          )}
        />
        <span
          className={cn(
            'absolute left-0 right-0 h-0.5 bg-current rounded-full',
            'transition-all duration-300',
            isOpen ? 'top-1/2 -translate-y-1/2 -rotate-45' : 'bottom-0',
          )}
        />
      </div>
    </button>
  );
}

export default MobileMenu;
