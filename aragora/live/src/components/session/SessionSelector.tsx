'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useSession, Session } from '@/hooks/useSession';

interface SessionSelectorProps {
  onSessionSelect?: (session: Session) => void;
  className?: string;
}

/**
 * Dropdown component for viewing and managing active sessions
 *
 * Shows current session with ability to view all sessions
 * and navigate to session management.
 */
export function SessionSelector({ onSessionSelect, className = '' }: SessionSelectorProps) {
  const { sessions, loading, error, currentSessionId, getLastActivityAge } = useSession();

  const [isOpen, setIsOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuItemsRef = useRef<(HTMLButtonElement | null)[]>([]);

  const currentSession = sessions.find((s) => s.id === currentSessionId);
  const otherSessions = sessions.filter((s) => s.id !== currentSessionId);

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
          setFocusedIndex((prev) => (prev + 1) % sessions.length);
          break;
        case 'ArrowUp':
          event.preventDefault();
          setFocusedIndex((prev) => (prev - 1 + sessions.length) % sessions.length);
          break;
        case 'Home':
          event.preventDefault();
          setFocusedIndex(0);
          break;
        case 'End':
          event.preventDefault();
          setFocusedIndex(sessions.length - 1);
          break;
        case 'Tab':
          setIsOpen(false);
          setFocusedIndex(-1);
          break;
      }
    },
    [isOpen, sessions.length],
  );

  // Focus menu item when focusedIndex changes
  useEffect(() => {
    if (isOpen && focusedIndex >= 0) {
      menuItemsRef.current[focusedIndex]?.focus();
    }
  }, [focusedIndex, isOpen]);

  const handleSessionClick = (session: Session) => {
    onSessionSelect?.(session);
    setIsOpen(false);
  };

  // Parse device icon from device name
  const getDeviceIcon = (deviceName: string): string => {
    const lower = deviceName.toLowerCase();
    if (lower.includes('mobile') || lower.includes('iphone') || lower.includes('android')) {
      return '[M]';
    }
    if (lower.includes('tablet') || lower.includes('ipad')) {
      return '[T]';
    }
    return '[D]'; // Desktop
  };

  if (loading && sessions.length === 0) {
    return (
      <div className={`text-xs font-theme-data text-text-muted animate-pulse ${className}`}>
        [LOADING SESSIONS...]
      </div>
    );
  }

  if (error && sessions.length === 0) {
    return (
      <div className={`text-xs font-theme-data text-warning ${className}`}>[SESSION ERROR]</div>
    );
  }

  return (
    <div className={`relative ${className}`} ref={menuRef} onKeyDown={handleKeyDown}>
      <button
        ref={buttonRef}
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Session selector"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        className="flex items-center gap-2 text-xs font-theme-data text-text-muted hover:text-[var(--acid-cyan)] transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-background"
      >
        <span className="text-[var(--accent)]/70">
          {currentSession ? getDeviceIcon(currentSession.device_name) : '[?]'}
        </span>
        <span className="hidden sm:inline truncate max-w-[150px]">
          {currentSession?.device_name || 'Unknown Session'}
        </span>
        <span className="text-text-muted/50">
          {sessions.length > 1 && `+${sessions.length - 1}`}
        </span>
        <span className="text-[var(--accent)]/50" aria-hidden="true">
          {isOpen ? '[^]' : '[v]'}
        </span>
      </button>

      {isOpen && (
        <div
          className="absolute right-0 top-full mt-2 w-72 bg-surface border border-[var(--accent)]/30 shadow-lg z-50"
          role="menu"
          aria-label="Session list"
        >
          {/* Current Session */}
          {currentSession && (
            <div className="p-3 border-b border-[var(--accent)]/20">
              <div className="text-xs font-theme-data text-[var(--accent)] mb-1">
                [CURRENT SESSION]
              </div>
              <div className="text-sm font-theme-data text-text truncate">
                {currentSession.device_name}
              </div>
              <div className="text-xs font-theme-data text-text-muted mt-1">
                Active {getLastActivityAge(currentSession)}
              </div>
            </div>
          )}

          {/* Other Sessions */}
          {otherSessions.length > 0 && (
            <div className="py-2">
              <div className="px-3 pb-1 text-xs font-theme-data text-text-muted">
                [OTHER SESSIONS: {otherSessions.length}]
              </div>
              {otherSessions.map((session, index) => (
                <button
                  key={session.id}
                  ref={(el) => {
                    menuItemsRef.current[index] = el;
                  }}
                  role="menuitem"
                  tabIndex={focusedIndex === index ? 0 : -1}
                  onClick={() => handleSessionClick(session)}
                  className="w-full px-3 py-2 text-left text-xs font-theme-data text-text-muted hover:bg-[var(--accent)]/10 hover:text-[var(--accent)] focus:bg-[var(--accent)]/10 focus:text-[var(--accent)] focus:outline-none transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--acid-cyan)]/70">
                      {getDeviceIcon(session.device_name)}
                    </span>
                    <span className="truncate flex-1">{session.device_name}</span>
                  </div>
                  <div className="text-text-muted/70 mt-0.5 pl-6">
                    Last active {getLastActivityAge(session)}
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* No Other Sessions */}
          {otherSessions.length === 0 && (
            <div className="p-3 text-xs font-theme-data text-text-muted">
              No other active sessions
            </div>
          )}

          {/* Session Count */}
          <div className="border-t border-[var(--accent)]/20 px-3 py-2 text-xs font-theme-data text-text-muted">
            {sessions.length} active session{sessions.length !== 1 ? 's' : ''}
          </div>
        </div>
      )}
    </div>
  );
}
