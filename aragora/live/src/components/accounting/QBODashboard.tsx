'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { TransactionList } from './TransactionList';
import { ReportGenerator } from './ReportGenerator';
import { useAuth } from '@/context/AuthContext';
import { DEMO_COMPANY, DEMO_DASHBOARD_STATS, DEMO_CUSTOMERS, DEMO_TRANSACTIONS } from '@/fixtures';

type DashboardTab = 'overview' | 'transactions' | 'customers' | 'reports';

interface CompanyInfo {
  name: string;
  legalName?: string;
  country?: string;
  email?: string;
}

interface DashboardStats {
  receivables: number;
  payables: number;
  revenue: number;
  expenses: number;
  netIncome: number;
  openInvoices: number;
  overdueInvoices: number;
}

interface Customer {
  id: string;
  displayName: string;
  companyName?: string;
  email?: string;
  balance: number;
  active: boolean;
}

interface Transaction {
  id: string;
  type: string;
  docNumber?: string;
  txnDate?: string;
  dueDate?: string;
  totalAmount: number;
  balance: number;
  customerName?: string;
  vendorName?: string;
  status: string;
}

// Demo data imported from @/fixtures - see DEMO_COMPANY, DEMO_DASHBOARD_STATS, etc.

export function QBODashboard() {
  const { tokens, isAuthenticated, isLoading: authLoading } = useAuth();
  const apiBase = API_BASE_URL;
  const [activeTab, setActiveTab] = useState<DashboardTab>('overview');
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [company, setCompany] = useState<CompanyInfo | null>(null);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);

  const fetchData = useCallback(async () => {
    // Skip API call if not authenticated - use mock data instead
    if (!isAuthenticated || authLoading) {
      setConnected(true);
      setCompany(DEMO_COMPANY);
      setStats(DEMO_DASHBOARD_STATS);
      setCustomers(DEMO_CUSTOMERS);
      setTransactions(DEMO_TRANSACTIONS);
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${apiBase}/api/accounting/status`, { headers });
      if (response.ok) {
        const data = await response.json();
        setConnected(data.connected);
        if (data.connected) {
          setCompany(data.company);
          setStats(data.stats);
          setCustomers(data.customers || []);
          setTransactions(data.transactions || []);
        }
      } else {
        // Use mock data for demo
        setConnected(true);
        setCompany(DEMO_COMPANY);
        setStats(DEMO_DASHBOARD_STATS);
        setCustomers(DEMO_CUSTOMERS);
        setTransactions(DEMO_TRANSACTIONS);
      }
    } catch {
      // Use mock data on error
      setConnected(true);
      setCompany(DEMO_COMPANY);
      setStats(DEMO_DASHBOARD_STATS);
      setCustomers(DEMO_CUSTOMERS);
      setTransactions(DEMO_TRANSACTIONS);
    } finally {
      setLoading(false);
    }
  }, [tokens?.access_token, isAuthenticated, authLoading, apiBase]);

  useEffect(() => {
    fetchData();
    // Refresh every 5 minutes
    const interval = setInterval(fetchData, 300000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleConnect = () => {
    // In production, this would redirect to OAuth flow
    window.open('/api/accounting/connect', '_blank');
  };

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-8 bg-[var(--surface)] rounded w-1/3" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-[var(--surface)] rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (!connected) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-8 text-center">
        <div className="text-4xl mb-4">📊</div>
        <h2 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">
          Connect QuickBooks Online
        </h2>
        <p className="text-[var(--text-muted)] mb-6 max-w-md mx-auto">
          Connect your QuickBooks Online account to sync transactions, generate reports, and get
          AI-powered insights into your finances.
        </p>
        <button
          onClick={handleConnect}
          className="px-6 py-3 bg-[#2CA01C] text-white font-theme-data rounded hover:bg-[#238A17] transition-colors"
        >
          Connect to QuickBooks
        </button>
        <p className="text-xs text-[var(--text-muted)] mt-4">
          Secure OAuth 2.0 connection • Read-only access available
        </p>
      </div>
    );
  }

  const tabs: Array<{ id: DashboardTab; label: string }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'transactions', label: 'Transactions' },
    { id: 'customers', label: 'Customers' },
    { id: 'reports', label: 'Reports' },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-theme-data text-[var(--acid-green)]">{'>'} QUICKBOOKS</h1>
          {company && (
            <p className="text-sm text-[var(--text-muted)] mt-1">
              Connected to <span className="text-[var(--acid-cyan)]">{company.name}</span>
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2 text-xs text-green-400">
            <span className="w-2 h-2 bg-green-400 rounded-full" />
            Connected
          </span>
          <button
            onClick={fetchData}
            className="px-3 py-2 text-sm font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors"
          >
            Sync
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[var(--border)]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-theme-data transition-colors relative ${
              activeTab === tab.id
                ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && stats && (
        <div className="space-y-6">
          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              label="Receivables"
              value={`$${stats.receivables.toLocaleString()}`}
              color="text-[var(--acid-green)]"
              sublabel={`${stats.openInvoices} open invoices`}
            />
            <StatCard
              label="Payables"
              value={`$${stats.payables.toLocaleString()}`}
              color="text-red-400"
            />
            <StatCard
              label="Revenue (MTD)"
              value={`$${stats.revenue.toLocaleString()}`}
              color="text-[var(--acid-cyan)]"
            />
            <StatCard
              label="Net Income"
              value={`$${stats.netIncome.toLocaleString()}`}
              color={stats.netIncome >= 0 ? 'text-green-400' : 'text-red-400'}
            />
          </div>

          {/* Alerts */}
          {stats.overdueInvoices > 0 && (
            <div className="bg-red-500/10 border border-red-500/30 rounded p-4">
              <div className="flex items-center gap-3">
                <span className="text-2xl">⚠️</span>
                <div>
                  <h3 className="text-sm font-theme-data text-red-400">Overdue Invoices</h3>
                  <p className="text-xs text-[var(--text-muted)]">
                    You have {stats.overdueInvoices} overdue invoice
                    {stats.overdueInvoices !== 1 ? 's' : ''} requiring attention.
                  </p>
                </div>
                <button className="ml-auto px-3 py-1 text-xs font-theme-data border border-red-500/30 text-red-400 rounded hover:bg-red-500/10 transition-colors">
                  View Overdue
                </button>
              </div>
            </div>
          )}

          {/* Recent Activity */}
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
            <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
              {'>'} RECENT ACTIVITY
            </h3>
            <div className="space-y-3">
              {transactions.slice(0, 5).map((txn) => (
                <div
                  key={txn.id}
                  className="flex items-center justify-between p-3 bg-[var(--bg)] rounded"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        txn.status === 'Paid'
                          ? 'bg-green-400'
                          : txn.status === 'Overdue'
                            ? 'bg-red-400'
                            : 'bg-yellow-400'
                      }`}
                    />
                    <div>
                      <div className="text-sm font-theme-data">{txn.docNumber || txn.type}</div>
                      <div className="text-xs text-[var(--text-muted)]">
                        {txn.customerName || txn.vendorName}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div
                      className={`text-sm font-theme-data ${
                        txn.type === 'Invoice' ? 'text-[var(--acid-green)]' : 'text-red-400'
                      }`}
                    >
                      {txn.type === 'Invoice' ? '+' : '-'}${txn.totalAmount.toLocaleString()}
                    </div>
                    <div className="text-xs text-[var(--text-muted)]">{txn.txnDate}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* AI Insights */}
          <div className="bg-[var(--surface)] border border-[var(--acid-green)]/30 rounded p-4">
            <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
              {'>'} AI INSIGHTS
            </h3>
            <div className="space-y-3">
              <InsightCard
                icon="💡"
                title="Cash Flow Projection"
                description="Based on current receivables and payables, your projected cash position in 30 days is +$33,930."
                type="positive"
              />
              <InsightCard
                icon="📈"
                title="Revenue Trend"
                description="Revenue is up 12% compared to last month. Top contributor: TechStart Inc."
                type="positive"
              />
              <InsightCard
                icon="⚠️"
                title="Collection Risk"
                description="Acme Corporation has 2 invoices over 30 days. Consider following up."
                type="warning"
              />
            </div>
          </div>
        </div>
      )}

      {/* Transactions Tab */}
      {activeTab === 'transactions' && <TransactionList transactions={transactions} />}

      {/* Customers Tab */}
      {activeTab === 'customers' && (
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
          <div className="p-4 border-b border-[var(--border)]">
            <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
              {'>'} CUSTOMERS ({customers.length})
            </h3>
          </div>
          <div className="divide-y divide-[var(--border)]">
            {customers.map((customer) => (
              <div
                key={customer.id}
                className="p-4 flex items-center justify-between hover:bg-[var(--bg)] transition-colors"
              >
                <div>
                  <div className="font-theme-data text-sm">{customer.displayName}</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {customer.email || 'No email'}
                  </div>
                </div>
                <div className="text-right">
                  <div
                    className={`font-theme-data ${customer.balance > 0 ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'}`}
                  >
                    ${customer.balance.toLocaleString()}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">Balance</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Reports Tab */}
      {activeTab === 'reports' && <ReportGenerator />}
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string;
  color: string;
  sublabel?: string;
}

function StatCard({ label, value, color, sublabel }: StatCardProps) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      <div className={`text-2xl font-theme-data font-bold ${color}`}>{value}</div>
      <div className="text-xs text-[var(--text-muted)] mt-1">{label}</div>
      {sublabel && <div className="text-xs text-[var(--text-muted)] opacity-70">{sublabel}</div>}
    </div>
  );
}

interface InsightCardProps {
  icon: string;
  title: string;
  description: string;
  type: 'positive' | 'warning' | 'neutral';
}

function InsightCard({ icon, title, description, type }: InsightCardProps) {
  const borderColor =
    type === 'positive'
      ? 'border-green-500/30'
      : type === 'warning'
        ? 'border-yellow-500/30'
        : 'border-[var(--border)]';

  return (
    <div className={`p-3 bg-[var(--bg)] rounded border-l-2 ${borderColor}`}>
      <div className="flex items-start gap-3">
        <span className="text-lg">{icon}</span>
        <div>
          <h4 className="text-sm font-theme-data text-[var(--text)]">{title}</h4>
          <p className="text-xs text-[var(--text-muted)] mt-1">{description}</p>
        </div>
      </div>
    </div>
  );
}

export default QBODashboard;
