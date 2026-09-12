'use client';

import { useState } from 'react';

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

interface TransactionListProps {
  transactions: Transaction[];
}

type FilterType = 'all' | 'Invoice' | 'Expense' | 'Payment';
type StatusFilter = 'all' | 'Open' | 'Paid' | 'Overdue';

export function TransactionList({ transactions }: TransactionListProps) {
  const [typeFilter, setTypeFilter] = useState<FilterType>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortField, setSortField] = useState<'date' | 'amount'>('date');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  // Filter transactions
  const filteredTransactions = transactions.filter((txn) => {
    if (typeFilter !== 'all' && txn.type !== typeFilter) return false;
    if (statusFilter !== 'all' && txn.status !== statusFilter) return false;
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      const matchesDoc = txn.docNumber?.toLowerCase().includes(query);
      const matchesCustomer = txn.customerName?.toLowerCase().includes(query);
      const matchesVendor = txn.vendorName?.toLowerCase().includes(query);
      if (!matchesDoc && !matchesCustomer && !matchesVendor) return false;
    }
    return true;
  });

  // Sort transactions
  const sortedTransactions = [...filteredTransactions].sort((a, b) => {
    let comparison = 0;
    if (sortField === 'date') {
      const dateA = a.txnDate ? new Date(a.txnDate).getTime() : 0;
      const dateB = b.txnDate ? new Date(b.txnDate).getTime() : 0;
      comparison = dateA - dateB;
    } else {
      comparison = a.totalAmount - b.totalAmount;
    }
    return sortDirection === 'asc' ? comparison : -comparison;
  });

  const toggleSort = (field: 'date' | 'amount') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'Paid':
        return 'text-green-400 bg-green-500/10';
      case 'Overdue':
        return 'text-red-400 bg-red-500/10';
      case 'Open':
        return 'text-yellow-400 bg-yellow-500/10';
      default:
        return 'text-[var(--text-muted)] bg-[var(--surface)]';
    }
  };

  const getTypeIcon = (type: string): string => {
    switch (type) {
      case 'Invoice':
        return '📄';
      case 'Expense':
        return '💸';
      case 'Payment':
        return '💰';
      case 'Bill':
        return '📋';
      default:
        return '📝';
    }
  };

  // Summary stats
  const totalReceivables = filteredTransactions
    .filter((t) => t.type === 'Invoice' && t.balance > 0)
    .reduce((sum, t) => sum + t.balance, 0);

  const totalPayables = filteredTransactions
    .filter((t) => (t.type === 'Expense' || t.type === 'Bill') && t.balance > 0)
    .reduce((sum, t) => sum + t.balance, 0);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <div className="flex flex-wrap items-center gap-4">
          {/* Search */}
          <div className="flex-1 min-w-0 sm:min-w-[200px]">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search transactions..."
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none"
            />
          </div>

          {/* Type Filter */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Type:</span>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as FilterType)}
              className="px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded text-sm font-theme-data text-[var(--text)]"
            >
              <option value="all">All</option>
              <option value="Invoice">Invoices</option>
              <option value="Expense">Expenses</option>
              <option value="Payment">Payments</option>
            </select>
          </div>

          {/* Status Filter */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              className="px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded text-sm font-theme-data text-[var(--text)]"
            >
              <option value="all">All</option>
              <option value="Open">Open</option>
              <option value="Paid">Paid</option>
              <option value="Overdue">Overdue</option>
            </select>
          </div>
        </div>

        {/* Summary */}
        <div className="flex items-center gap-6 mt-4 pt-4 border-t border-[var(--border)]">
          <div>
            <span className="text-xs text-[var(--text-muted)]">Showing: </span>
            <span className="text-sm font-theme-data text-[var(--text)]">
              {sortedTransactions.length}
            </span>
            <span className="text-xs text-[var(--text-muted)]"> of {transactions.length}</span>
          </div>
          {totalReceivables > 0 && (
            <div>
              <span className="text-xs text-[var(--text-muted)]">Open Receivables: </span>
              <span className="text-sm font-theme-data text-[var(--acid-green)]">
                ${totalReceivables.toLocaleString()}
              </span>
            </div>
          )}
          {totalPayables > 0 && (
            <div>
              <span className="text-xs text-[var(--text-muted)]">Open Payables: </span>
              <span className="text-sm font-theme-data text-red-400">
                ${totalPayables.toLocaleString()}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Transaction Table */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-12 gap-4 p-3 bg-[var(--bg)] border-b border-[var(--border)] text-xs font-theme-data text-[var(--text-muted)]">
          <div className="col-span-1">Type</div>
          <div className="col-span-2">Number</div>
          <div className="col-span-3">Customer/Vendor</div>
          <div
            className="col-span-2 cursor-pointer hover:text-[var(--acid-green)] flex items-center gap-1"
            onClick={() => toggleSort('date')}
          >
            Date
            {sortField === 'date' && <span>{sortDirection === 'asc' ? '↑' : '↓'}</span>}
          </div>
          <div
            className="col-span-2 text-right cursor-pointer hover:text-[var(--acid-green)] flex items-center justify-end gap-1"
            onClick={() => toggleSort('amount')}
          >
            Amount
            {sortField === 'amount' && <span>{sortDirection === 'asc' ? '↑' : '↓'}</span>}
          </div>
          <div className="col-span-2 text-right">Status</div>
        </div>

        {/* Rows */}
        {sortedTransactions.length === 0 ? (
          <div className="p-8 text-center text-[var(--text-muted)] font-theme-data text-sm">
            No transactions found matching your filters.
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {sortedTransactions.map((txn) => (
              <div
                key={txn.id}
                className="grid grid-cols-12 gap-4 p-3 hover:bg-[var(--bg)] transition-colors items-center"
              >
                <div className="col-span-1 text-lg">{getTypeIcon(txn.type)}</div>
                <div className="col-span-2">
                  <div className="font-theme-data text-sm text-[var(--text)]">
                    {txn.docNumber || '-'}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">{txn.type}</div>
                </div>
                <div className="col-span-3 truncate">
                  <div className="text-sm text-[var(--text)]">
                    {txn.customerName || txn.vendorName || '-'}
                  </div>
                </div>
                <div className="col-span-2">
                  <div className="text-sm text-[var(--text)]">{txn.txnDate || '-'}</div>
                  {txn.dueDate && txn.status !== 'Paid' && (
                    <div className="text-xs text-[var(--text-muted)]">Due: {txn.dueDate}</div>
                  )}
                </div>
                <div className="col-span-2 text-right">
                  <div
                    className={`font-theme-data text-sm ${
                      txn.type === 'Invoice' || txn.type === 'Payment'
                        ? 'text-[var(--acid-green)]'
                        : 'text-red-400'
                    }`}
                  >
                    {txn.type === 'Invoice' || txn.type === 'Payment' ? '+' : '-'}$
                    {txn.totalAmount.toLocaleString()}
                  </div>
                  {txn.balance > 0 && txn.balance !== txn.totalAmount && (
                    <div className="text-xs text-[var(--text-muted)]">
                      Bal: ${txn.balance.toLocaleString()}
                    </div>
                  )}
                </div>
                <div className="col-span-2 text-right">
                  <span
                    className={`px-2 py-1 text-xs font-theme-data rounded ${getStatusColor(txn.status)}`}
                  >
                    {txn.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default TransactionList;
