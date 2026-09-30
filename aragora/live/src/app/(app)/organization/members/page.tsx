'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { useAuth } from '@/context/AuthContext';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

interface Member {
  id: string;
  email: string;
  name: string | null;
  role: 'owner' | 'admin' | 'member';
  joined_at: string;
}

interface OrganizationDetails {
  id: string;
  name: string;
  owner_id: string;
  member_limit: number;
}

export default function OrganizationMembersPage() {
  const { organization, tokens, user } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [orgDetails, setOrgDetails] = useState<OrganizationDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member');
  const [inviting, setInviting] = useState(false);
  const [inviteSuccess, setInviteSuccess] = useState<string | null>(null);
  const orgId = organization?.id;
  const accessToken = tokens?.access_token;

  const fetchData = useCallback(async () => {
    if (!orgId || !accessToken) {
      return;
    }
    try {
      const [membersRes, orgRes] = await Promise.all([
        fetch(`${API_BASE}/api/org/${orgId}/members`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
        fetch(`${API_BASE}/api/org/${orgId}`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
      ]);

      if (!membersRes.ok) {
        throw new Error('Failed to fetch members');
      }

      const membersData = await membersRes.json();
      setMembers(membersData.members || []);

      if (orgRes.ok) {
        const orgData = await orgRes.json();
        setOrgDetails(orgData.organization);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load members');
    } finally {
      setLoading(false);
    }
  }, [orgId, accessToken]);

  useEffect(() => {
    if (orgId && accessToken) {
      fetchData();
    }
  }, [orgId, accessToken, fetchData]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;

    setInviting(true);
    setError(null);
    setInviteSuccess(null);

    try {
      const response = await fetch(`${API_BASE}/api/org/${orgId}/invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to send invite');
      }

      setInviteSuccess(`Invitation sent to ${inviteEmail}`);
      setInviteEmail('');
      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to invite');
    } finally {
      setInviting(false);
    }
  };

  const handleRoleChange = async (memberId: string, newRole: 'admin' | 'member') => {
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/org/${orgId}/members/${memberId}/role`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ role: newRole }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to update role');
      }

      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update role');
    }
  };

  const handleRemoveMember = async (memberId: string, memberEmail: string) => {
    if (!confirm(`Remove ${memberEmail} from the organization?`)) return;

    setError(null);

    try {
      const response = await fetch(`${API_BASE}/api/org/${orgId}/members/${memberId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${accessToken}` },
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to remove member');
      }

      await fetchData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove member');
    }
  };

  const isOwner = user?.id === orgDetails?.owner_id;
  const isAdmin = members.find((m) => m.id === user?.id)?.role === 'admin' || isOwner;

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'owner':
        return 'text-warning border-warning/30 bg-warning/10';
      case 'admin':
        return 'text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/10';
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
              className="pb-2 font-theme-data text-sm text-text-muted hover:text-text transition-colors"
            >
              SETTINGS
            </Link>
            <Link
              href="/organization/members"
              className="pb-2 font-theme-data text-sm text-[var(--accent)] border-b-2 border-[var(--accent)]"
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

          {inviteSuccess && (
            <div className="mb-6 p-4 border border-[var(--accent)]/50 bg-[var(--accent)]/10 text-[var(--accent)] text-sm font-theme-data">
              {inviteSuccess}
              <button onClick={() => setInviteSuccess(null)} className="ml-4 text-xs underline">
                Dismiss
              </button>
            </div>
          )}

          {loading ? (
            <div className="text-center py-12 font-theme-data text-text-muted">
              Loading members...
            </div>
          ) : (
            <div className="space-y-6">
              {/* Invite Form - Admin/Owner Only */}
              {isAdmin && (
                <div className="border border-[var(--accent)]/30 bg-surface/30 p-6">
                  <h2 className="text-lg font-theme-data text-[var(--acid-cyan)] mb-4">
                    INVITE MEMBER
                  </h2>
                  <form onSubmit={handleInvite} className="flex flex-col md:flex-row gap-4">
                    <div className="flex-1">
                      <label htmlFor="invite-email" className="sr-only">
                        Email address
                      </label>
                      <input
                        id="invite-email"
                        type="email"
                        value={inviteEmail}
                        onChange={(e) => setInviteEmail(e.target.value)}
                        placeholder="email@example.com"
                        aria-label="Email address to invite"
                        className="w-full bg-bg border border-[var(--accent)]/30 px-4 py-2 font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none"
                        required
                      />
                    </div>
                    <div>
                      <label htmlFor="invite-role" className="sr-only">
                        Role
                      </label>
                      <select
                        id="invite-role"
                        value={inviteRole}
                        onChange={(e) => setInviteRole(e.target.value as 'admin' | 'member')}
                        aria-label="Role for invited member"
                        className="bg-bg border border-[var(--accent)]/30 px-4 py-2 font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none"
                      >
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </select>
                    </div>
                    <button
                      type="submit"
                      disabled={inviting || !inviteEmail.trim()}
                      className="px-6 py-2 font-theme-data text-sm border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
                    >
                      {inviting ? 'SENDING...' : 'INVITE'}
                    </button>
                  </form>
                  {orgDetails && (
                    <div className="mt-3 text-xs font-theme-data text-text-muted">
                      {members.length} /{' '}
                      {orgDetails.member_limit === 999999 ? 'Unlimited' : orgDetails.member_limit}{' '}
                      members
                    </div>
                  )}
                </div>
              )}

              {/* Member List */}
              <div className="border border-[var(--accent)]/30 bg-surface/30 p-6">
                <h2 className="text-lg font-theme-data text-[var(--acid-cyan)] mb-4">
                  MEMBERS ({members.length})
                </h2>

                {members.length === 0 ? (
                  <div className="text-center py-8 font-theme-data text-text-muted">
                    No members found
                  </div>
                ) : (
                  <div className="space-y-3">
                    {members.map((member) => (
                      <div
                        key={member.id}
                        className="flex items-center justify-between p-4 border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors"
                      >
                        <div className="flex items-center gap-4">
                          <div>
                            <div className="font-theme-data text-sm text-text">
                              {member.name || member.email}
                            </div>
                            {member.name && (
                              <div className="text-xs font-theme-data text-text-muted">
                                {member.email}
                              </div>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-4">
                          <span
                            className={`px-2 py-1 border font-theme-data text-xs uppercase ${getRoleBadgeColor(member.role)}`}
                          >
                            {member.role}
                          </span>

                          {/* Role change dropdown - only for non-owners */}
                          {isAdmin && member.role !== 'owner' && member.id !== user?.id && (
                            <select
                              value={member.role}
                              onChange={(e) =>
                                handleRoleChange(member.id, e.target.value as 'admin' | 'member')
                              }
                              className="bg-bg border border-[var(--accent)]/30 px-2 py-1 font-theme-data text-xs text-text focus:border-[var(--accent)] focus:outline-none"
                              aria-label={`Change role for ${member.email}`}
                            >
                              <option value="member">Member</option>
                              <option value="admin">Admin</option>
                            </select>
                          )}

                          {/* Remove button - only for non-owners */}
                          {isAdmin && member.role !== 'owner' && member.id !== user?.id && (
                            <button
                              onClick={() => handleRemoveMember(member.id, member.email)}
                              className="text-xs font-theme-data text-warning hover:text-warning/80 transition-colors"
                              aria-label={`Remove ${member.email} from organization`}
                            >
                              [REMOVE]
                            </button>
                          )}

                          {member.id === user?.id && (
                            <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                              (you)
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Info Box */}
              <div className="border border-[var(--accent)]/20 bg-surface/20 p-4">
                <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-2">
                  ROLE PERMISSIONS
                </h3>
                <div className="space-y-1 text-xs font-theme-data text-text-muted">
                  <div>
                    <span className="text-warning">Owner:</span> Full access, billing, delete
                    organization
                  </div>
                  <div>
                    <span className="text-[var(--acid-cyan)]">Admin:</span> Manage members,
                    settings, create debates
                  </div>
                  <div>
                    <span className="text-text">Member:</span> View organization, participate in
                    debates
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </ProtectedRoute>
  );
}
