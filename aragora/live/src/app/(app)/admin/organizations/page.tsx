'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { MemberTable, Member } from '@/components/admin/MemberTable';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface Organization {
  id: string;
  name: string;
  slug: string;
  tier: string;
  debates_used_this_month: number;
  debates_limit: number;
  owner_id: string;
  owner_email?: string;
  member_count: number;
  stripe_customer_id?: string;
  stripe_subscription_id?: string;
  billing_cycle_start: string;
  created_at: string;
  updated_at: string;
}

interface OrganizationsResponse {
  organizations: Organization[];
  total: number;
  limit: number;
  offset: number;
}

interface OrgMember extends Member {
  org_role: string;
}

interface APIKey {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at?: string;
  is_active: boolean;
}

function TierBadge({ tier }: { tier: string }) {
  const colors: Record<string, string> = {
    free: 'bg-text-muted/20 text-text-muted border-text-muted/40',
    starter: 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40',
    professional: 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40',
    enterprise: 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40',
  };

  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${colors[tier] || colors.free}`}
    >
      {tier.replace('_', ' ').toUpperCase()}
    </span>
  );
}

function UsageBar({ used, limit }: { used: number; limit: number }) {
  const percent = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const color =
    percent >= 90 ? 'bg-acid-red' : percent >= 70 ? 'bg-acid-yellow' : 'bg-[var(--accent)]';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-bg rounded overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${percent}%` }} />
      </div>
      <span className="font-theme-data text-xs text-text-muted whitespace-nowrap">
        {used}/{limit}
      </span>
    </div>
  );
}

// Organization Detail Modal
function OrgDetailModal({
  isOpen,
  onClose,
  organization,
  onLoadMembers,
  onLoadAPIKeys,
}: {
  isOpen: boolean;
  onClose: () => void;
  organization: Organization | null;
  onLoadMembers: (orgId: string) => Promise<OrgMember[]>;
  onLoadAPIKeys: (orgId: string) => Promise<APIKey[]>;
}) {
  const [activeTab, setActiveTab] = useState<'details' | 'members' | 'api-keys'>('details');
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [apiKeys, setApiKeys] = useState<APIKey[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && organization) {
      setActiveTab('details');
      setMembers([]);
      setApiKeys([]);
    }
  }, [isOpen, organization]);

  const loadMembers = async () => {
    if (!organization) return;
    setLoading(true);
    try {
      const data = await onLoadMembers(organization.id);
      setMembers(data);
    } catch {
      // Error handled silently
    } finally {
      setLoading(false);
    }
  };

  const loadAPIKeys = async () => {
    if (!organization) return;
    setLoading(true);
    try {
      const data = await onLoadAPIKeys(organization.id);
      setApiKeys(data);
    } catch {
      // Error handled silently
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'members' && members.length === 0) {
      loadMembers();
    } else if (activeTab === 'api-keys' && apiKeys.length === 0) {
      loadAPIKeys();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Load data only on tab change, not on data updates
  }, [activeTab]);

  if (!isOpen || !organization) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-surface border border-[var(--accent)]/40 rounded-lg shadow-xl w-full max-w-3xl max-h-[80vh] overflow-hidden z-10">
        {/* Header */}
        <div className="p-4 border-b border-[var(--accent)]/20">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-theme-data text-lg text-[var(--accent)]">{organization.name}</h2>
              <p className="font-theme-data text-xs text-text-muted">/{organization.slug}</p>
            </div>
            <div className="flex items-center gap-2">
              <TierBadge tier={organization.tier} />
              <button
                onClick={onClose}
                className="p-1 text-text-muted hover:text-text transition-colors"
              >
                x
              </button>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[var(--accent)]/20">
          {(['details', 'members', 'api-keys'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 font-theme-data text-sm transition-colors ${
                activeTab === tab
                  ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              {tab.replace('-', ' ').toUpperCase()}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto max-h-[calc(80vh-150px)]">
          {activeTab === 'details' && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="card p-4">
                  <div className="font-theme-data text-xs text-text-muted">Organization ID</div>
                  <div className="font-theme-data text-sm text-[var(--acid-cyan)] break-all">
                    {organization.id}
                  </div>
                </div>
                <div className="card p-4">
                  <div className="font-theme-data text-xs text-text-muted">Created</div>
                  <div className="font-theme-data text-sm text-text">
                    {new Date(organization.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>

              <div className="card p-4">
                <div className="font-theme-data text-xs text-text-muted mb-2">
                  Debates Usage (This Month)
                </div>
                <UsageBar
                  used={organization.debates_used_this_month}
                  limit={organization.debates_limit}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="card p-4">
                  <div className="font-theme-data text-xs text-text-muted">Members</div>
                  <div className="font-theme-data text-2xl text-[var(--accent)]">
                    {organization.member_count}
                  </div>
                </div>
                <div className="card p-4">
                  <div className="font-theme-data text-xs text-text-muted">Billing</div>
                  <div className="font-theme-data text-sm">
                    {organization.stripe_customer_id ? (
                      <span className="text-[var(--accent)]">Connected</span>
                    ) : (
                      <span className="text-text-muted">Not set up</span>
                    )}
                  </div>
                </div>
              </div>

              {organization.owner_email && (
                <div className="card p-4">
                  <div className="font-theme-data text-xs text-text-muted">Owner</div>
                  <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                    {organization.owner_email}
                  </div>
                </div>
              )}

              <div className="card p-4">
                <div className="font-theme-data text-xs text-text-muted">Billing Cycle</div>
                <div className="font-theme-data text-sm text-text">
                  Started: {new Date(organization.billing_cycle_start).toLocaleDateString()}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'members' && (
            <div>
              {loading ? (
                <div className="text-center py-8 font-theme-data text-text-muted animate-pulse">
                  Loading members...
                </div>
              ) : members.length === 0 ? (
                <div className="text-center py-8 font-theme-data text-text-muted">
                  No members found
                </div>
              ) : (
                <MemberTable data={members} loading={loading} pageSize={10} actions={[]} />
              )}
            </div>
          )}

          {activeTab === 'api-keys' && (
            <div>
              {loading ? (
                <div className="text-center py-8 font-theme-data text-text-muted animate-pulse">
                  Loading API keys...
                </div>
              ) : apiKeys.length === 0 ? (
                <div className="text-center py-8 font-theme-data text-text-muted">
                  No API keys found
                </div>
              ) : (
                <div className="space-y-2">
                  {apiKeys.map((key) => (
                    <div key={key.id} className="card p-3 flex items-center justify-between">
                      <div>
                        <div className="font-theme-data text-sm text-text">{key.name}</div>
                        <div className="font-theme-data text-xs text-[var(--acid-cyan)]">
                          {key.key_prefix}...
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        <div className="font-theme-data text-xs text-text-muted">
                          {key.last_used_at
                            ? `Last used: ${new Date(key.last_used_at).toLocaleDateString()}`
                            : 'Never used'}
                        </div>
                        <span
                          className={`px-2 py-0.5 text-xs font-theme-data rounded border ${
                            key.is_active
                              ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40'
                              : 'bg-acid-red/20 text-acid-red border-acid-red/40'
                          }`}
                        >
                          {key.is_active ? 'ACTIVE' : 'REVOKED'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function OrganizationsAdminPageContent() {
  const { config: backendConfig } = useBackend();
  const { user, isAuthenticated, tokens } = useAuth();
  const searchParams = useSearchParams();
  const token = tokens?.access_token;

  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [tierFilter, setTierFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);

  const limit = 20;

  const fetchOrganizations = useCallback(async () => {
    if (!token) return;

    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams({
        limit: String(limit),
        offset: String((page - 1) * limit),
      });
      if (tierFilter) params.set('tier', tierFilter);
      if (searchQuery) params.set('search', searchQuery);

      const res = await fetch(`${backendConfig.api}/api/v1/admin/organizations?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        if (res.status === 403) throw new Error('Admin access required');
        throw new Error(`Failed to fetch organizations: ${res.status}`);
      }

      const data: OrganizationsResponse = await res.json();
      setOrganizations(data.organizations);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch organizations');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, token, page, tierFilter, searchQuery]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchOrganizations();
    }
  }, [fetchOrganizations, isAuthenticated]);

  // Check for action param
  useEffect(() => {
    if (searchParams.get('action') === 'create') {
      // Could open create modal here
    }
  }, [searchParams]);

  const loadOrgMembers = async (orgId: string): Promise<OrgMember[]> => {
    if (!token) return [];

    const res = await fetch(`${backendConfig.api}/api/v1/admin/organizations/${orgId}/members`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!res.ok) return [];

    const data = await res.json();
    return (data.members || []).map(
      (m: {
        id: string;
        email: string;
        name?: string;
        role: string;
        org_role: string;
        is_active: boolean;
        joined_at: string;
        last_active?: string;
      }) => ({
        id: m.id,
        name: m.name || m.email.split('@')[0],
        email: m.email,
        role: m.role,
        org_role: m.org_role,
        status: m.is_active ? 'active' : 'inactive',
        joinedAt: m.joined_at,
        lastActive: m.last_active,
      }),
    );
  };

  const loadOrgAPIKeys = async (orgId: string): Promise<APIKey[]> => {
    if (!token) return [];

    const res = await fetch(`${backendConfig.api}/api/v1/admin/organizations/${orgId}/api-keys`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!res.ok) return [];

    const data = await res.json();
    return data.api_keys || [];
  };

  const handleOrgClick = (org: Organization) => {
    setSelectedOrg(org);
    setShowDetailModal(true);
  };

  const _isAdmin = isAuthenticated && (user?.role === 'admin' || user?.role === 'owner');

  // Calculate tier stats
  const tierStats = organizations.reduce(
    (acc, org) => {
      acc[org.tier] = (acc[org.tier] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <AdminLayout
      title="Organization Management"
      description="Manage organizations, subscriptions, and team settings."
      actions={
        <button
          onClick={fetchOrganizations}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      }
    >
      {error && (
        <div className="card p-4 mb-6 border-acid-red/40 bg-acid-red/10">
          <p className="text-acid-red font-theme-data text-sm">{error}</p>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 mb-6">
        <div className="flex-1 min-w-0 sm:min-w-[200px]">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search by name or slug..."
            className="w-full bg-surface border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2 focus:outline-none focus:border-[var(--accent)]"
          />
        </div>
        <select
          value={tierFilter}
          onChange={(e) => {
            setTierFilter(e.target.value);
            setPage(1);
          }}
          aria-label="Filter by tier"
          className="bg-surface border border-[var(--accent)]/40 text-text font-theme-data text-sm rounded px-3 py-2"
        >
          <option value="">All Tiers</option>
          <option value="free">Free</option>
          <option value="starter">Starter</option>
          <option value="professional">Pro</option>
          <option value="enterprise">Enterprise</option>
        </select>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Total</div>
          <div className="font-theme-data text-2xl text-[var(--accent)]">{total}</div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Free</div>
          <div className="font-theme-data text-2xl text-text-muted">{tierStats.free || 0}</div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Starter</div>
          <div className="font-theme-data text-2xl text-[var(--acid-cyan)]">
            {tierStats.starter || 0}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Pro</div>
          <div className="font-theme-data text-2xl text-[var(--accent)]">
            {tierStats.professional || 0}
          </div>
        </div>
        <div className="card p-4">
          <div className="font-theme-data text-xs text-text-muted">Enterprise</div>
          <div className="font-theme-data text-2xl text-[var(--acid-yellow)]">
            {tierStats.enterprise || 0}
          </div>
        </div>
      </div>

      {/* Organizations Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-surface border-b border-[var(--accent)]/20">
              <tr>
                <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                  ORGANIZATION
                </th>
                <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                  TIER
                </th>
                <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                  MEMBERS
                </th>
                <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                  USAGE
                </th>
                <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                  BILLING
                </th>
                <th className="text-left px-4 py-3 font-theme-data text-xs text-text-muted">
                  CREATED
                </th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center">
                    <div className="font-theme-data text-text-muted animate-pulse">Loading...</div>
                  </td>
                </tr>
              )}
              {!loading && organizations.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center">
                    <div className="font-theme-data text-text-muted">No organizations found</div>
                  </td>
                </tr>
              )}
              {!loading &&
                organizations.map((org) => (
                  <tr
                    key={org.id}
                    className="border-b border-[var(--accent)]/10 hover:bg-surface/50 cursor-pointer"
                    onClick={() => handleOrgClick(org)}
                  >
                    <td className="px-4 py-3">
                      <div className="font-theme-data text-sm text-text">{org.name}</div>
                      <div className="font-theme-data text-xs text-[var(--acid-cyan)]">
                        /{org.slug}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <TierBadge tier={org.tier} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-theme-data text-sm text-text">{org.member_count}</div>
                    </td>
                    <td className="px-4 py-3 min-w-[150px]">
                      <UsageBar used={org.debates_used_this_month} limit={org.debates_limit} />
                    </td>
                    <td className="px-4 py-3">
                      {org.stripe_customer_id ? (
                        <span className="px-2 py-0.5 text-xs font-theme-data rounded border bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/40">
                          CONNECTED
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 text-xs font-theme-data rounded border bg-text-muted/20 text-text-muted border-text-muted/40">
                          NOT SET
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-theme-data text-xs text-text-muted">
                        {new Date(org.created_at).toLocaleDateString()}
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {Math.ceil(total / limit) > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--accent)]/20">
            <div className="font-theme-data text-xs text-text-muted">
              Showing {(page - 1) * limit + 1} to {Math.min(page * limit, total)} of {total}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1 font-theme-data text-sm text-[var(--acid-cyan)] hover:text-[var(--accent)] disabled:text-text-muted disabled:cursor-not-allowed transition-colors"
              >
                &lt; PREV
              </button>
              <span className="font-theme-data text-sm text-text-muted">
                Page {page} of {Math.ceil(total / limit)}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(Math.ceil(total / limit), p + 1))}
                disabled={page >= Math.ceil(total / limit)}
                className="px-3 py-1 font-theme-data text-sm text-[var(--acid-cyan)] hover:text-[var(--accent)] disabled:text-text-muted disabled:cursor-not-allowed transition-colors"
              >
                NEXT &gt;
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Organization Detail Modal */}
      <OrgDetailModal
        isOpen={showDetailModal}
        onClose={() => {
          setShowDetailModal(false);
          setSelectedOrg(null);
        }}
        organization={selectedOrg}
        onLoadMembers={loadOrgMembers}
        onLoadAPIKeys={loadOrgAPIKeys}
      />
    </AdminLayout>
  );
}

export default function OrganizationsAdminPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-center font-theme-data text-text-muted">Loading...</div>}
    >
      <OrganizationsAdminPageContent />
    </Suspense>
  );
}
