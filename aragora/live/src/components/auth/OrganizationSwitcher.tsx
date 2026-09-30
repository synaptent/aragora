'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '@/context/AuthContext';

interface OrganizationSwitcherProps {
  /** Compact mode shows only current org name with minimal styling */
  compact?: boolean;
  /** Callback when organization is switched */
  onSwitch?: (orgId: string) => void;
}

/**
 * Organization switcher component for multi-org support.
 * Allows users to view and switch between their organizations.
 */
export function OrganizationSwitcher({ compact = false, onSwitch }: OrganizationSwitcherProps) {
  const {
    organization,
    organizations,
    isLoadingOrganizations,
    switchOrganization,
    refreshOrganizations,
  } = useAuth();

  const [isOpen, setIsOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Handle keyboard navigation
  const handleKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      setIsOpen(false);
      buttonRef.current?.focus();
    }
  }, []);

  const handleSwitch = async (orgId: string) => {
    if (orgId === organization?.id) {
      setIsOpen(false);
      return;
    }

    setSwitching(orgId);
    setError(null);

    const result = await switchOrganization(orgId);

    if (result.success) {
      setIsOpen(false);
      onSwitch?.(orgId);
    } else {
      setError(result.error || 'Failed to switch organization');
    }

    setSwitching(null);
  };

  const handleSetDefault = async (orgId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSwitching(orgId);
    setError(null);

    const result = await switchOrganization(orgId, true);

    if (!result.success) {
      setError(result.error || 'Failed to set default organization');
    }

    setSwitching(null);
  };

  // Don't show if user only has one org or none
  if (organizations.length <= 1) {
    if (compact && organization) {
      return <div className="text-xs font-theme-data text-text-muted">{organization.name}</div>;
    }
    return null;
  }

  const getTierColor = (tier: string) => {
    switch (tier) {
      case 'free':
        return 'text-text-muted';
      case 'starter':
        return 'text-[var(--acid-cyan)]';
      case 'professional':
        return 'text-[var(--accent)]';
      case 'enterprise':
        return 'text-warning';
      default:
        return 'text-text-muted';
    }
  };

  const getRoleBadge = (role: 'member' | 'admin' | 'owner') => {
    switch (role) {
      case 'owner':
        return 'border-warning/30 text-warning';
      case 'admin':
        return 'border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)]';
      default:
        return 'border-text-muted/30 text-text-muted';
    }
  };

  if (compact) {
    return (
      <div className="relative" ref={menuRef} onKeyDown={handleKeyDown}>
        <button
          ref={buttonRef}
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-1 text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
          aria-label="Switch organization"
          aria-haspopup="listbox"
          aria-expanded={isOpen}
        >
          <span className="truncate max-w-[120px]">{organization?.name || 'Select org'}</span>
          <span className="text-[var(--accent)]/50">{isOpen ? '^' : 'v'}</span>
        </button>

        {isOpen && (
          <div
            className="absolute left-0 top-full mt-1 w-56 bg-surface border border-[var(--accent)]/30 shadow-lg z-50"
            role="listbox"
            aria-label="Organizations"
          >
            {organizations.map((userOrg) => (
              <button
                key={userOrg.org_id}
                onClick={() => handleSwitch(userOrg.org_id)}
                disabled={switching === userOrg.org_id}
                role="option"
                aria-selected={userOrg.org_id === organization?.id}
                className={`w-full px-3 py-2 text-left text-xs font-theme-data transition-colors ${
                  userOrg.org_id === organization?.id
                    ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                    : 'text-text-muted hover:bg-[var(--accent)]/5 hover:text-text'
                } ${switching === userOrg.org_id ? 'opacity-50' : ''}`}
              >
                <div className="flex items-center justify-between">
                  <span className="truncate">{userOrg.organization.name}</span>
                  {userOrg.org_id === organization?.id && (
                    <span className="text-[var(--accent)]">*</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="relative" ref={menuRef} onKeyDown={handleKeyDown}>
      <button
        ref={buttonRef}
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 bg-surface border border-[var(--accent)]/30 text-xs font-theme-data text-text hover:border-[var(--accent)]/50 transition-colors"
        aria-label="Switch organization"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span className="w-5 h-5 rounded bg-[var(--accent)]/20 flex items-center justify-center text-[var(--accent)] text-[10px]">
          {organization?.name?.[0]?.toUpperCase() || '?'}
        </span>
        <div className="flex flex-col items-start">
          <span className="text-text truncate max-w-[150px]">
            {organization?.name || 'Select organization'}
          </span>
          {organization && (
            <span className={`text-[10px] uppercase ${getTierColor(organization.tier)}`}>
              {organization.tier}
            </span>
          )}
        </div>
        <span className="ml-auto text-[var(--accent)]/50">{isOpen ? '[^]' : '[v]'}</span>
      </button>

      {isOpen && (
        <div
          className="absolute left-0 top-full mt-2 w-72 bg-surface border border-[var(--accent)]/30 shadow-lg z-50"
          role="listbox"
          aria-label="Organizations"
        >
          {/* Header */}
          <div className="px-4 py-2 border-b border-[var(--accent)]/20 flex items-center justify-between">
            <span className="text-xs font-theme-data text-text-muted">YOUR ORGANIZATIONS</span>
            <button
              onClick={() => refreshOrganizations()}
              disabled={isLoadingOrganizations}
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors disabled:opacity-50"
            >
              {isLoadingOrganizations ? '[...]' : '[REFRESH]'}
            </button>
          </div>

          {/* Error message */}
          {error && (
            <div className="px-4 py-2 bg-warning/10 border-b border-warning/20 text-xs font-theme-data text-warning">
              {error}
            </div>
          )}

          {/* Organization list */}
          <div className="max-h-64 overflow-y-auto">
            {organizations.map((userOrg) => (
              <button
                key={userOrg.org_id}
                onClick={() => handleSwitch(userOrg.org_id)}
                disabled={switching === userOrg.org_id}
                role="option"
                aria-selected={userOrg.org_id === organization?.id}
                className={`w-full px-4 py-3 text-left transition-colors ${
                  userOrg.org_id === organization?.id
                    ? 'bg-[var(--accent)]/10'
                    : 'hover:bg-surface-hover'
                } ${switching === userOrg.org_id ? 'opacity-50' : ''}`}
              >
                <div className="flex items-start gap-3">
                  <span className="w-8 h-8 rounded bg-[var(--accent)]/20 flex items-center justify-center text-[var(--accent)] text-sm flex-shrink-0">
                    {userOrg.organization.name[0].toUpperCase()}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-theme-data text-text truncate">
                        {userOrg.organization.name}
                      </span>
                      {userOrg.is_default && (
                        <span className="text-[10px] font-theme-data text-[var(--acid-cyan)]">
                          (default)
                        </span>
                      )}
                      {userOrg.org_id === organization?.id && (
                        <span className="text-[var(--accent)]">*</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span
                        className={`text-[10px] font-theme-data uppercase ${getTierColor(userOrg.organization.tier)}`}
                      >
                        {userOrg.organization.tier}
                      </span>
                      <span
                        className={`text-[10px] font-theme-data px-1 border rounded ${getRoleBadge(userOrg.role)}`}
                      >
                        {userOrg.role}
                      </span>
                    </div>
                  </div>
                  {userOrg.org_id !== organization?.id && !userOrg.is_default && (
                    <button
                      onClick={(e) => handleSetDefault(userOrg.org_id, e)}
                      className="text-[10px] font-theme-data text-text-muted hover:text-[var(--acid-cyan)] transition-colors"
                      title="Set as default"
                    >
                      [SET DEFAULT]
                    </button>
                  )}
                </div>
              </button>
            ))}
          </div>

          {/* Footer */}
          <div className="px-4 py-2 border-t border-[var(--accent)]/20">
            <span className="text-[10px] font-theme-data text-text-muted">
              {organizations.length} organization{organizations.length !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default OrganizationSwitcher;
