'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useAuth } from '@/context/AuthContext';
import { OrganizationSwitcher } from './OrganizationSwitcher';

export function UserMenu() {
  const { user, organization, organizations, isAuthenticated, isLoading, logout } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuItemsRef = useRef<(HTMLAnchorElement | HTMLButtonElement | null)[]>([]);

  const menuItems = ['billing', 'settings', 'developer', 'ab-testing', 'logout'];

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setFocusedIndex(-1);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Handle keyboard navigation
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (!isOpen) {
        if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') {
          event.preventDefault();
          setIsOpen(true);
          setFocusedIndex(0);
        }
        return;
      }

      switch (event.key) {
        case 'Escape':
          event.preventDefault();
          setIsOpen(false);
          setFocusedIndex(-1);
          buttonRef.current?.focus();
          break;
        case 'ArrowDown':
          event.preventDefault();
          setFocusedIndex((prev) => (prev + 1) % menuItems.length);
          break;
        case 'ArrowUp':
          event.preventDefault();
          setFocusedIndex((prev) => (prev - 1 + menuItems.length) % menuItems.length);
          break;
        case 'Home':
          event.preventDefault();
          setFocusedIndex(0);
          break;
        case 'End':
          event.preventDefault();
          setFocusedIndex(menuItems.length - 1);
          break;
        case 'Tab':
          setIsOpen(false);
          setFocusedIndex(-1);
          break;
      }
    },
    [isOpen, menuItems.length],
  );

  // Focus menu item when focusedIndex changes
  useEffect(() => {
    if (isOpen && focusedIndex >= 0) {
      menuItemsRef.current[focusedIndex]?.focus();
    }
  }, [focusedIndex, isOpen]);

  if (isLoading) {
    return (
      <div className="text-xs font-theme-data text-text-muted animate-pulse">[LOADING...]</div>
    );
  }

  if (!isAuthenticated || !user) {
    return (
      <div className="flex items-center gap-3">
        <Link
          href="/auth/login"
          className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
        >
          [LOGIN]
        </Link>
        <Link
          href="/signup"
          className="text-xs font-theme-data px-3 py-1 bg-[var(--accent)]/10 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors"
        >
          [SIGN UP]
        </Link>
      </div>
    );
  }

  return (
    <div className="relative" ref={menuRef} onKeyDown={handleKeyDown}>
      <button
        ref={buttonRef}
        onClick={() => setIsOpen(!isOpen)}
        aria-label="User menu"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        className="flex items-center gap-2 text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-background"
      >
        <span className="w-6 h-6 rounded-full bg-[var(--accent)]/20 border border-[var(--accent)]/50 flex items-center justify-center text-[var(--accent)]">
          {user.name?.[0]?.toUpperCase() || user.email[0].toUpperCase()}
        </span>
        <span className="hidden sm:inline">{user.name || user.email.split('@')[0]}</span>
        <span className="text-[var(--accent)]/50" aria-hidden="true">
          {isOpen ? '[^]' : '[v]'}
        </span>
      </button>

      {isOpen && (
        <div
          className="absolute right-0 top-full mt-2 w-64 bg-surface border border-[var(--accent)]/30 shadow-lg z-50"
          role="menu"
          aria-label="User menu"
        >
          {/* User Info */}
          <div className="p-4 border-b border-[var(--accent)]/20">
            <div className="text-sm font-theme-data text-text">{user.name || 'Anonymous'}</div>
            <div className="text-xs font-theme-data text-text-muted truncate">{user.email}</div>
            {organization && (
              <div className="mt-2 text-xs font-theme-data text-[var(--acid-cyan)]">
                ORG: {organization.name}
                <span className="ml-2 px-1 py-0.5 bg-[var(--accent)]/10 text-[var(--accent)] uppercase">
                  {organization.tier}
                </span>
              </div>
            )}
          </div>

          {/* Organization Switcher - shown when user has multiple orgs */}
          {organizations.length > 1 && (
            <div className="p-3 border-b border-[var(--accent)]/20">
              <OrganizationSwitcher compact onSwitch={() => setIsOpen(false)} />
            </div>
          )}

          {/* Menu Items */}
          <div className="py-2">
            <Link
              ref={(el) => {
                menuItemsRef.current[0] = el;
              }}
              href="/billing"
              role="menuitem"
              tabIndex={focusedIndex === 0 ? 0 : -1}
              className="block px-4 py-2 text-xs font-theme-data text-text-muted hover:bg-[var(--accent)]/10 hover:text-[var(--accent)] focus:bg-[var(--accent)]/10 focus:text-[var(--accent)] focus:outline-none transition-colors"
              onClick={() => setIsOpen(false)}
            >
              [BILLING & USAGE]
            </Link>
            <Link
              ref={(el) => {
                menuItemsRef.current[1] = el;
              }}
              href="/settings"
              role="menuitem"
              tabIndex={focusedIndex === 1 ? 0 : -1}
              className="block px-4 py-2 text-xs font-theme-data text-text-muted hover:bg-[var(--accent)]/10 hover:text-[var(--accent)] focus:bg-[var(--accent)]/10 focus:text-[var(--accent)] focus:outline-none transition-colors"
              onClick={() => setIsOpen(false)}
            >
              [SETTINGS]
            </Link>
            <Link
              ref={(el) => {
                menuItemsRef.current[2] = el;
              }}
              href="/developer"
              role="menuitem"
              tabIndex={focusedIndex === 2 ? 0 : -1}
              className="block px-4 py-2 text-xs font-theme-data text-text-muted hover:bg-[var(--accent)]/10 hover:text-[var(--accent)] focus:bg-[var(--accent)]/10 focus:text-[var(--accent)] focus:outline-none transition-colors"
              onClick={() => setIsOpen(false)}
            >
              [DEVELOPER]
            </Link>
            <Link
              ref={(el) => {
                menuItemsRef.current[3] = el;
              }}
              href="/ab-testing"
              role="menuitem"
              tabIndex={focusedIndex === 3 ? 0 : -1}
              className="block px-4 py-2 text-xs font-theme-data text-text-muted hover:bg-[var(--accent)]/10 hover:text-[var(--accent)] focus:bg-[var(--accent)]/10 focus:text-[var(--accent)] focus:outline-none transition-colors"
              onClick={() => setIsOpen(false)}
            >
              [A/B TESTING]
            </Link>
          </div>

          {/* Logout */}
          <div className="border-t border-[var(--accent)]/20 py-2">
            <button
              ref={(el) => {
                menuItemsRef.current[4] = el;
              }}
              role="menuitem"
              tabIndex={focusedIndex === 4 ? 0 : -1}
              onClick={() => {
                setIsOpen(false);
                logout();
              }}
              className="w-full px-4 py-2 text-xs font-theme-data text-warning hover:bg-warning/10 focus:bg-warning/10 focus:outline-none transition-colors text-left"
              aria-label="Logout"
            >
              [LOGOUT]
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
