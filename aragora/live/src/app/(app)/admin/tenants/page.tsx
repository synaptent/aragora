'use client';

import { useState } from 'react';

interface Tenant {
  id: string;
  name: string;
  tier: 'free' | 'standard' | 'enterprise';
  status: 'active' | 'suspended' | 'pending';
  createdAt: string;
  usage: { apiCalls: number; storageBytes: number; debates: number };
  quotas: { apiCallsLimit: number; storageLimit: number; debateLimit: number };
}

const defaultQuotas: Record<Tenant['tier'], Tenant['quotas']> = {
  free: { apiCallsLimit: 1000, storageLimit: 100 * 1024 * 1024, debateLimit: 10 },
  standard: { apiCallsLimit: 10000, storageLimit: 1024 * 1024 * 1024, debateLimit: 100 },
  enterprise: { apiCallsLimit: 100000, storageLimit: 10 * 1024 * 1024 * 1024, debateLimit: 1000 },
};

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
}

function TenantCard({
  tenant,
  onEdit,
  onSuspend,
  onDelete,
}: {
  tenant: Tenant;
  onEdit: (t: Tenant) => void;
  onSuspend: (t: Tenant) => void;
  onDelete: (t: Tenant) => void;
}) {
  const usagePercent = {
    api: (tenant.usage.apiCalls / tenant.quotas.apiCallsLimit) * 100,
    storage: (tenant.usage.storageBytes / tenant.quotas.storageLimit) * 100,
    debates: (tenant.usage.debates / tenant.quotas.debateLimit) * 100,
  };

  const tierColors = { free: 'bg-gray-100', standard: 'bg-blue-100', enterprise: 'bg-purple-100' };
  const statusColors = {
    active: 'bg-green-100',
    suspended: 'bg-red-100',
    pending: 'bg-yellow-100',
  };

  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm">
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-lg font-semibold">{tenant.name}</h3>
          <p className="text-sm text-gray-500">{tenant.id}</p>
        </div>
        <div className="flex gap-2">
          <span className={'px-2 py-1 rounded text-xs font-medium ' + tierColors[tenant.tier]}>
            {tenant.tier.toUpperCase()}
          </span>
          <span className={'px-2 py-1 rounded text-xs font-medium ' + statusColors[tenant.status]}>
            {tenant.status.toUpperCase()}
          </span>
        </div>
      </div>
      <div className="space-y-3">
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span>API Calls</span>
            <span>{tenant.usage.apiCalls.toLocaleString()}</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={
                'h-2 rounded-full ' + (usagePercent.api > 90 ? 'bg-red-500' : 'bg-green-500')
              }
              style={{ width: Math.min(usagePercent.api, 100) + '%' }}
            />
          </div>
        </div>
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span>Storage</span>
            <span>{formatBytes(tenant.usage.storageBytes)}</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={
                'h-2 rounded-full ' + (usagePercent.storage > 90 ? 'bg-red-500' : 'bg-green-500')
              }
              style={{ width: Math.min(usagePercent.storage, 100) + '%' }}
            />
          </div>
        </div>
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span>Debates</span>
            <span>{tenant.usage.debates.toLocaleString()}</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={
                'h-2 rounded-full ' + (usagePercent.debates > 90 ? 'bg-red-500' : 'bg-green-500')
              }
              style={{ width: Math.min(usagePercent.debates, 100) + '%' }}
            />
          </div>
        </div>
      </div>
      <div className="flex gap-2 mt-4 pt-4 border-t">
        <button
          onClick={() => onEdit(tenant)}
          className="px-3 py-1 text-sm bg-blue-50 text-blue-600 rounded"
        >
          Edit
        </button>
        <button
          onClick={() => onSuspend(tenant)}
          className="px-3 py-1 text-sm bg-yellow-50 text-yellow-600 rounded"
        >
          {tenant.status === 'suspended' ? 'Activate' : 'Suspend'}
        </button>
        <button
          onClick={() => onDelete(tenant)}
          className="px-3 py-1 text-sm bg-red-50 text-red-600 rounded"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([
    {
      id: 'tenant-001',
      name: 'Acme Corporation',
      tier: 'enterprise',
      status: 'active',
      createdAt: '2024-01-15',
      usage: { apiCalls: 85000, storageBytes: 5 * 1024 * 1024 * 1024, debates: 450 },
      quotas: defaultQuotas.enterprise,
    },
    {
      id: 'tenant-002',
      name: 'Startup Inc',
      tier: 'standard',
      status: 'active',
      createdAt: '2024-06-20',
      usage: { apiCalls: 4500, storageBytes: 256 * 1024 * 1024, debates: 25 },
      quotas: defaultQuotas.standard,
    },
    {
      id: 'tenant-003',
      name: 'Test User',
      tier: 'free',
      status: 'pending',
      createdAt: '2024-12-01',
      usage: { apiCalls: 100, storageBytes: 10 * 1024 * 1024, debates: 2 },
      quotas: defaultQuotas.free,
    },
  ]);
  const [search, setSearch] = useState('');

  const filteredTenants = tenants.filter((t) =>
    t.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="max-w-7xl mx-auto p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">Tenant Management</h1>
          <p className="text-gray-500">Manage organizations and their quotas</p>
        </div>
        <button className="px-4 py-2 bg-blue-600 text-white rounded-md">Create Tenant</button>
      </div>
      <input
        type="text"
        placeholder="Search tenants..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full px-4 py-2 border rounded-md mb-6"
      />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredTenants.map((tenant) => (
          <TenantCard
            key={tenant.id}
            tenant={tenant}
            onEdit={() => {}}
            onSuspend={(t) =>
              setTenants(
                tenants.map((x) =>
                  x.id === t.id
                    ? { ...x, status: x.status === 'suspended' ? 'active' : 'suspended' }
                    : x,
                ),
              )
            }
            onDelete={(t) => setTenants(tenants.filter((x) => x.id !== t.id))}
          />
        ))}
      </div>
    </div>
  );
}
