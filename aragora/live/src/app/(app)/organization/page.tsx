'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { useAuth } from '@/context/AuthContext';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

interface OrganizationDetails {
  id: string;
  name: string;
  slug: string;
  tier: string;
  owner_id: string;
  member_count: number;
  member_limit: number;
  created_at: string;
}

export default function OrganizationPage() {
  const { organization, tokens, user } = useAuth();
  const [orgDetails, setOrgDetails] = useState<OrganizationDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editName, setEditName] = useState('');
  const [saving, setSaving] = useState(false);
  const orgId = organization?.id;
  const accessToken = tokens?.access_token;

  const fetchOrgDetails = useCallback(async () => {
    if (!orgId || !accessToken) {
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/org/${orgId}`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch organization details');
      }

      const data = await response.json();
      setOrgDetails(data.organization);
      setEditName(data.organization.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load organization');
    } finally {
      setLoading(false);
    }
  }, [orgId, accessToken]);

  useEffect(() => {
    if (orgId && accessToken) {
      fetchOrgDetails();
    }
  }, [orgId, accessToken, fetchOrgDetails]);

  const handleSave = async () => {
    if (!editName.trim()) {
      setError('Organization name cannot be empty');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/org/${orgId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ name: editName.trim() }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to update organization');
      }

      await fetchOrgDetails();
      setEditMode(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const isOwner = user?.id === orgDetails?.owner_id;

  const getTierBadgeColor = (tier: string) => {
    switch (tier) {
      case 'free':
        return 'text-text-muted border-text-muted/30';
      case 'starter':
        return 'text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30';
      case 'professional':
        return 'text-[var(--accent)] border-[var(--accent)]/30';
      case 'enterprise':
        return 'text-warning border-warning/30';
      default:
        return 'text-text-muted border-text-muted/30';
    }
  };

  return (
    <ProtectedRoute>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <Link
              href="/"
              className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              [DASHBOARD]
            </Link>
          </div>
        </header>

        {/* Content */}
        <div className="max-w-4xl mx-auto px-4 py-8">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)]">ORGANIZATION SETTINGS</h1>
          </div>

          {/* Sub-navigation */}
          <div className="flex gap-4 mb-6 border-b border-[var(--accent)]/30">
            <Link
              href="/organization"
              className="pb-2 font-theme-data text-sm text-[var(--accent)] border-b-2 border-[var(--accent)]"
            >
              SETTINGS
            </Link>
            <Link
              href="/organization/members"
              className="pb-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
            >
              MEMBERS
            </Link>
          </div>

          {error && (
            <div className="mb-6 p-4 border border-warning/50 bg-warning/10 text-warning text-sm font-theme-data">
              {error}
              <button onClick={() => setError(null)} className="ml-4 text-xs underline">
                Dismiss
              </button>
            </div>
          )}

          {loading ? (
            <div className="text-center py-12 font-theme-data text-text-muted">
              Loading organization details...
            </div>
          ) : orgDetails ? (
            <div className="space-y-6">
              {/* Organization Info Card */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-6">
                <div className="flex items-start justify-between mb-6">
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">
                      ORGANIZATION NAME
                    </div>
                    {editMode ? (
                      <div className="flex gap-3">
                        <input
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-lg text-[var(--accent)] focus:border-[var(--accent)] focus:outline-none"
                        />
                        <button
                          onClick={handleSave}
                          disabled={saving}
                          className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
                        >
                          {saving ? 'SAVING...' : 'SAVE'}
                        </button>
                        <button
                          onClick={() => {
                            setEditMode(false);
                            setEditName(orgDetails.name);
                          }}
                          className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
                        >
                          CANCEL
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-4">
                        <div className="text-2xl font-theme-data text-[var(--accent)]">
                          {orgDetails.name}
                        </div>
                        {isOwner && (
                          <button
                            onClick={() => setEditMode(true)}
                            className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                          >
                            [EDIT]
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <div
                    className={`px-3 py-1 border font-theme-data text-sm uppercase ${getTierBadgeColor(orgDetails.tier)}`}
                  >
                    {orgDetails.tier}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">SLUG</div>
                    <div className="text-sm font-theme-data text-text">{orgDetails.slug}</div>
                  </div>
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">MEMBERS</div>
                    <div className="text-sm font-theme-data text-text">
                      {orgDetails.member_count} /{' '}
                      {orgDetails.member_limit === 999999 ? 'Unlimited' : orgDetails.member_limit}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">CREATED</div>
                    <div className="text-sm font-theme-data text-text">
                      {new Date(orgDetails.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-theme-data text-text-muted mb-1">YOUR ROLE</div>
                    <div className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase">
                      {isOwner ? 'Owner' : 'Member'}
                    </div>
                  </div>
                </div>
              </div>

              {/* Quick Actions */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-6">
                <h2 className="text-lg font-theme-data text-[var(--acid-cyan)] mb-4">
                  QUICK ACTIONS
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Link
                    href="/organization/members"
                    className="block p-4 border border-[var(--accent)]/20 hover:border-[var(--accent)]/50 transition-colors"
                  >
                    <div className="text-sm font-theme-data text-[var(--accent)] mb-1">
                      Manage Members
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">
                      Add, remove, or update member roles
                    </div>
                  </Link>
                  <Link
                    href="/billing"
                    className="block p-4 border border-[var(--accent)]/20 hover:border-[var(--accent)]/50 transition-colors"
                  >
                    <div className="text-sm font-theme-data text-[var(--accent)] mb-1">
                      Billing & Subscription
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">
                      Manage your subscription and usage
                    </div>
                  </Link>
                </div>
              </div>

              {/* Danger Zone - Owner Only */}
              {isOwner && (
                <div className="border border-warning/30 bg-warning/5 p-6">
                  <h2 className="text-lg font-theme-data text-warning mb-4">DANGER ZONE</h2>
                  <div className="text-sm font-theme-data text-text-muted mb-4">
                    These actions are irreversible. Please be certain.
                  </div>
                  <button
                    className="px-4 py-2 font-theme-data text-sm border border-warning/50 text-warning hover:bg-warning/10 transition-colors opacity-50 cursor-not-allowed"
                    disabled
                    title="Contact support to delete organization"
                  >
                    DELETE ORGANIZATION
                  </button>
                  <div className="text-xs font-theme-data text-text-muted mt-2">
                    Contact support to delete your organization
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-12">
              <div className="font-theme-data text-text-muted mb-4">No organization found</div>
              <div className="text-sm font-theme-data text-text-muted">
                You are not part of any organization
              </div>
            </div>
          )}
        </div>
      </main>
    </ProtectedRoute>
  );
}
