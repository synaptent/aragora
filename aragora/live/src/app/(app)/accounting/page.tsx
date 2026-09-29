'use client';

import { Suspense, useState } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { QBODashboard } from '@/components/accounting/QBODashboard';
import { BankConnectionCard } from '@/components/accounting/BankConnectionCard';
import { ReconciliationProgress } from '@/components/accounting/ReconciliationProgress';
import { DiscrepancyQueue } from '@/components/accounting/DiscrepancyQueue';
import { PayrollStatusPanel } from '@/components/accounting/PayrollStatusPanel';

type AccountingTab = 'overview' | 'banking' | 'reconciliation' | 'payroll';

function LoadingFallback() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="h-8 bg-[var(--surface)] rounded w-1/3" />
      <div className="grid grid-cols-4 gap-4">
        <div className="h-24 bg-[var(--surface)] rounded" />
        <div className="h-24 bg-[var(--surface)] rounded" />
        <div className="h-24 bg-[var(--surface)] rounded" />
        <div className="h-24 bg-[var(--surface)] rounded" />
      </div>
      <div className="h-64 bg-[var(--surface)] rounded" />
    </div>
  );
}

export default function AccountingPage() {
  const [activeTab, setActiveTab] = useState<AccountingTab>('overview');

  const tabs: Array<{ id: AccountingTab; label: string; icon: string }> = [
    { id: 'overview', label: 'QuickBooks', icon: '📊' },
    { id: 'banking', label: 'Banking', icon: '🏦' },
    { id: 'reconciliation', label: 'Reconciliation', icon: '🔄' },
    { id: 'payroll', label: 'Payroll', icon: '💰' },
  ];

  return (
    <div className="min-h-screen bg-background">
      <Scanlines />
      <CRTVignette />

      <div className="container mx-auto px-4 py-6 max-w-7xl">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-theme-data text-[var(--acid-green)]">{'>'} ACCOUNTING</h1>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-[var(--border)] mb-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-3 text-sm font-theme-data transition-colors flex items-center gap-2 ${
                activeTab === tab.id
                  ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)] -mb-px'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              <span>{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <Suspense fallback={<LoadingFallback />}>
          {activeTab === 'overview' && (
            <PanelErrorBoundary panelName="QuickBooks Dashboard">
              <QBODashboard />
            </PanelErrorBoundary>
          )}

          {activeTab === 'banking' && (
            <div className="space-y-6">
              <PanelErrorBoundary panelName="Bank Connection">
                <BankConnectionCard />
              </PanelErrorBoundary>

              {/* Bank Transaction Summary */}
              <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
                <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
                  {'>'} RECENT BANK TRANSACTIONS
                </h3>
                <p className="text-xs text-[var(--text-muted)]">
                  Connect a bank account to view transactions and enable automatic reconciliation.
                </p>
              </div>
            </div>
          )}

          {activeTab === 'reconciliation' && (
            <div className="space-y-6">
              <PanelErrorBoundary panelName="Reconciliation Progress">
                <ReconciliationProgress />
              </PanelErrorBoundary>

              <PanelErrorBoundary panelName="Discrepancy Queue">
                <DiscrepancyQueue />
              </PanelErrorBoundary>
            </div>
          )}

          {activeTab === 'payroll' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <PanelErrorBoundary panelName="Payroll Status">
                <PayrollStatusPanel />
              </PanelErrorBoundary>

              {/* Payroll-to-QBO Mapping */}
              <div className="bg-[var(--surface)] border border-[var(--border)] rounded">
                <div className="p-4 border-b border-[var(--border)]">
                  <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
                    {'>'} QBO ACCOUNT MAPPING
                  </h3>
                  <p className="text-xs text-[var(--text-muted)] mt-1">
                    Configure how payroll data maps to QuickBooks accounts
                  </p>
                </div>
                <div className="p-4 space-y-3">
                  <AccountMappingRow
                    label="Gross Wages"
                    account="6000 - Wages Expense"
                    type="expense"
                  />
                  <AccountMappingRow
                    label="Employer Taxes"
                    account="6100 - Payroll Tax Expense"
                    type="expense"
                  />
                  <AccountMappingRow
                    label="Employee Taxes Withheld"
                    account="2100 - Payroll Liabilities"
                    type="liability"
                  />
                  <AccountMappingRow
                    label="Net Pay"
                    account="1000 - Checking Account"
                    type="asset"
                  />
                </div>
                <div className="p-4 border-t border-[var(--border)]">
                  <button className="w-full px-4 py-2 text-xs font-theme-data text-[var(--text-muted)] border border-dashed border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 hover:text-[var(--acid-green)] transition-colors">
                    Configure Mapping
                  </button>
                </div>
              </div>
            </div>
          )}
        </Suspense>

        {/* Integration Status Footer */}
        <div className="mt-8 p-4 bg-[var(--surface)] border border-[var(--border)] rounded">
          <h4 className="text-xs text-[var(--text-muted)] mb-3">Connected Services</h4>
          <div className="flex flex-wrap gap-4">
            <IntegrationBadge name="QuickBooks Online" status="connected" />
            <IntegrationBadge name="Plaid (Banking)" status="connected" />
            <IntegrationBadge name="Gusto (Payroll)" status="connected" />
          </div>
        </div>
      </div>
    </div>
  );
}

interface AccountMappingRowProps {
  label: string;
  account: string;
  type: 'expense' | 'liability' | 'asset';
}

function AccountMappingRow({ label, account, type }: AccountMappingRowProps) {
  const typeColors = {
    expense: 'text-red-400',
    liability: 'text-yellow-400',
    asset: 'text-[var(--acid-green)]',
  };

  return (
    <div className="flex items-center justify-between p-3 bg-[var(--bg)] rounded">
      <span className="text-sm font-theme-data">{label}</span>
      <span className={`text-xs font-theme-data ${typeColors[type]}`}>{account}</span>
    </div>
  );
}

interface IntegrationBadgeProps {
  name: string;
  status: 'connected' | 'disconnected' | 'error';
}

function IntegrationBadge({ name, status }: IntegrationBadgeProps) {
  const statusConfig = {
    connected: {
      bg: 'bg-green-500/10',
      border: 'border-green-500/30',
      text: 'text-green-400',
      dot: 'bg-green-400',
    },
    disconnected: {
      bg: 'bg-[var(--bg)]',
      border: 'border-[var(--border)]',
      text: 'text-[var(--text-muted)]',
      dot: 'bg-[var(--text-muted)]',
    },
    error: {
      bg: 'bg-red-500/10',
      border: 'border-red-500/30',
      text: 'text-red-400',
      dot: 'bg-red-400',
    },
  };

  const config = statusConfig[status];

  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded border ${config.bg} ${config.border}`}
    >
      <span className={`w-2 h-2 rounded-full ${config.dot}`} />
      <span className={`text-xs font-theme-data ${config.text}`}>{name}</span>
    </div>
  );
}
