'use client';

import { useState, useRef, useCallback } from 'react';

interface Expense {
  id: string;
  vendorName: string;
  amount: number;
  currency: string;
  date: string;
  category: string;
  status: string;
  paymentMethod: string;
  description: string;
  isReimbursable: boolean;
  isBillable: boolean;
  totalAmount: number;
  confidenceScore: number;
  tags: string[];
}

interface ExpenseStats {
  totalExpenses: number;
  totalAmount: number;
  pendingCount: number;
  pendingAmount: number;
  byCategory: Record<string, number>;
  byMonth: Record<string, number>;
  topVendors: { vendor: string; total: number }[];
  avgExpense: number;
}

interface ExpenseTrackerProps {
  expenses?: Expense[];
  stats?: ExpenseStats;
  onUploadReceipt?: (file: File) => Promise<void>;
  onCreateExpense?: (data: Partial<Expense>) => Promise<void>;
  onApproveExpense?: (id: string) => Promise<void>;
  onRejectExpense?: (id: string, reason: string) => Promise<void>;
  onSyncToQBO?: (ids: string[]) => Promise<void>;
}

type ViewMode = 'list' | 'grid' | 'stats';
type StatusFilter = 'all' | 'pending' | 'processed' | 'approved' | 'synced' | 'rejected';

const EXPENSE_CATEGORIES = [
  { value: 'travel', label: 'Travel', icon: '✈️' },
  { value: 'meals', label: 'Meals', icon: '🍽️' },
  { value: 'office_supplies', label: 'Office Supplies', icon: '📎' },
  { value: 'software', label: 'Software', icon: '💻' },
  { value: 'hardware', label: 'Hardware', icon: '🖥️' },
  { value: 'professional_services', label: 'Professional Services', icon: '👔' },
  { value: 'marketing', label: 'Marketing', icon: '📢' },
  { value: 'utilities', label: 'Utilities', icon: '💡' },
  { value: 'telecommunications', label: 'Telecommunications', icon: '📱' },
  { value: 'subscriptions', label: 'Subscriptions', icon: '📄' },
  { value: 'other', label: 'Other', icon: '📦' },
];

const PAYMENT_METHODS = [
  { value: 'credit_card', label: 'Credit Card' },
  { value: 'debit_card', label: 'Debit Card' },
  { value: 'cash', label: 'Cash' },
  { value: 'check', label: 'Check' },
  { value: 'wire', label: 'Wire' },
  { value: 'ach', label: 'ACH' },
];

export function ExpenseTracker({
  expenses = [],
  stats,
  onUploadReceipt,
  onCreateExpense,
  onApproveExpense,
  onRejectExpense,
  onSyncToQBO,
}: ExpenseTrackerProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedExpenses, setSelectedExpenses] = useState<Set<string>>(new Set());
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Form state for creating expense
  const [newExpense, setNewExpense] = useState({
    vendorName: '',
    amount: '',
    date: new Date().toISOString().split('T')[0],
    category: 'other',
    paymentMethod: 'credit_card',
    description: '',
    isReimbursable: false,
    tags: '',
  });

  // Filter expenses
  const filteredExpenses = expenses.filter((expense) => {
    if (statusFilter !== 'all' && expense.status !== statusFilter) return false;
    if (categoryFilter !== 'all' && expense.category !== categoryFilter) return false;
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      const matchesVendor = expense.vendorName.toLowerCase().includes(query);
      const matchesDescription = expense.description.toLowerCase().includes(query);
      if (!matchesVendor && !matchesDescription) return false;
    }
    return true;
  });

  // Drag and drop handlers
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);

      const files = Array.from(e.dataTransfer.files);
      const imageFiles = files.filter(
        (f) => f.type.startsWith('image/') || f.type === 'application/pdf',
      );

      for (const file of imageFiles) {
        if (onUploadReceipt) {
          setUploadProgress(0);
          await onUploadReceipt(file);
          setUploadProgress(100);
          setTimeout(() => setUploadProgress(null), 1000);
        }
      }
    },
    [onUploadReceipt],
  );

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && onUploadReceipt) {
      for (const file of Array.from(files)) {
        setUploadProgress(0);
        await onUploadReceipt(file);
        setUploadProgress(100);
        setTimeout(() => setUploadProgress(null), 1000);
      }
    }
  };

  const handleCreateExpense = async () => {
    if (onCreateExpense) {
      await onCreateExpense({
        vendorName: newExpense.vendorName,
        amount: parseFloat(newExpense.amount) || 0,
        date: newExpense.date,
        category: newExpense.category,
        paymentMethod: newExpense.paymentMethod,
        description: newExpense.description,
        isReimbursable: newExpense.isReimbursable,
        tags: newExpense.tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      } as Partial<Expense>);
      setShowCreateModal(false);
      setNewExpense({
        vendorName: '',
        amount: '',
        date: new Date().toISOString().split('T')[0],
        category: 'other',
        paymentMethod: 'credit_card',
        description: '',
        isReimbursable: false,
        tags: '',
      });
    }
  };

  const handleBulkApprove = async () => {
    if (onApproveExpense) {
      for (const id of selectedExpenses) {
        await onApproveExpense(id);
      }
      setSelectedExpenses(new Set());
    }
  };

  const handleSyncSelected = async () => {
    if (onSyncToQBO) {
      await onSyncToQBO(Array.from(selectedExpenses));
      setSelectedExpenses(new Set());
    }
  };

  const toggleExpenseSelection = (id: string) => {
    const newSelection = new Set(selectedExpenses);
    if (newSelection.has(id)) {
      newSelection.delete(id);
    } else {
      newSelection.add(id);
    }
    setSelectedExpenses(newSelection);
  };

  const selectAllVisible = () => {
    setSelectedExpenses(new Set(filteredExpenses.map((e) => e.id)));
  };

  const clearSelection = () => {
    setSelectedExpenses(new Set());
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'synced':
        return 'text-green-400 bg-green-500/10';
      case 'approved':
        return 'text-blue-400 bg-blue-500/10';
      case 'processed':
      case 'categorized':
        return 'text-yellow-400 bg-yellow-500/10';
      case 'pending':
        return 'text-orange-400 bg-orange-500/10';
      case 'rejected':
      case 'duplicate':
        return 'text-red-400 bg-red-500/10';
      default:
        return 'text-[var(--text-muted)] bg-[var(--surface)]';
    }
  };

  const getCategoryIcon = (category: string): string => {
    return EXPENSE_CATEGORIES.find((c) => c.value === category)?.icon || '📦';
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-2xl">💳</span>
          <h2 className="text-lg font-bold text-[var(--text)]">Expense Tracker</h2>
        </div>
        <div className="flex items-center gap-2">
          {/* View Mode Toggle */}
          <div className="flex items-center gap-1 bg-[var(--surface)] border border-[var(--border)] rounded p-1">
            <button
              onClick={() => setViewMode('list')}
              className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
                viewMode === 'list'
                  ? 'bg-[var(--acid-green)] text-black'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              List
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
                viewMode === 'grid'
                  ? 'bg-[var(--acid-green)] text-black'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              Grid
            </button>
            <button
              onClick={() => setViewMode('stats')}
              className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
                viewMode === 'stats'
                  ? 'bg-[var(--acid-green)] text-black'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              Stats
            </button>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-3 py-1.5 bg-[var(--acid-green)] text-black rounded text-sm font-theme-data hover:opacity-90 transition-opacity"
          >
            + Add Expense
          </button>
        </div>
      </div>

      {/* Upload Area */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
          isDragging
            ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10'
            : 'border-[var(--border)] hover:border-[var(--acid-green)]/50'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,application/pdf"
          multiple
          onChange={handleFileSelect}
          className="hidden"
        />
        <div className="text-3xl mb-2">📸</div>
        <p className="text-sm text-[var(--text)]">
          Drop receipts here or{' '}
          <button
            onClick={() => fileInputRef.current?.click()}
            className="text-[var(--acid-green)] hover:underline"
          >
            browse files
          </button>
        </p>
        <p className="text-xs text-[var(--text-muted)] mt-1">Supports PNG, JPG, and PDF</p>
        {uploadProgress !== null && (
          <div className="mt-2">
            <div className="h-1 bg-[var(--border)] rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--acid-green)] transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Filters & Actions */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <div className="flex flex-wrap items-center gap-4">
          {/* Search */}
          <div className="flex-1 min-w-0 sm:min-w-[200px]">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search expenses..."
              className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none"
            />
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
              <option value="pending">Pending</option>
              <option value="processed">Processed</option>
              <option value="approved">Approved</option>
              <option value="synced">Synced</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>

          {/* Category Filter */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">Category:</span>
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded text-sm font-theme-data text-[var(--text)]"
            >
              <option value="all">All</option>
              {EXPENSE_CATEGORIES.map((cat) => (
                <option key={cat.value} value={cat.value}>
                  {cat.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Bulk Actions */}
        {selectedExpenses.size > 0 && (
          <div className="flex items-center gap-4 mt-4 pt-4 border-t border-[var(--border)]">
            <span className="text-sm text-[var(--text)]">{selectedExpenses.size} selected</span>
            <button
              onClick={handleBulkApprove}
              className="px-2 py-1 text-xs font-theme-data bg-blue-500/20 text-blue-400 rounded hover:bg-blue-500/30"
            >
              Approve Selected
            </button>
            <button
              onClick={handleSyncSelected}
              className="px-2 py-1 text-xs font-theme-data bg-green-500/20 text-green-400 rounded hover:bg-green-500/30"
            >
              Sync to QBO
            </button>
            <button
              onClick={clearSelection}
              className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)]"
            >
              Clear
            </button>
          </div>
        )}
      </div>

      {/* Content based on view mode */}
      {viewMode === 'stats' && stats ? (
        <StatsView stats={stats} />
      ) : viewMode === 'grid' ? (
        <GridView
          expenses={filteredExpenses}
          selectedExpenses={selectedExpenses}
          onToggleSelect={toggleExpenseSelection}
          getStatusColor={getStatusColor}
          getCategoryIcon={getCategoryIcon}
        />
      ) : (
        <ListView
          expenses={filteredExpenses}
          selectedExpenses={selectedExpenses}
          onToggleSelect={toggleExpenseSelection}
          onSelectAll={selectAllVisible}
          getStatusColor={getStatusColor}
          getCategoryIcon={getCategoryIcon}
          onApprove={onApproveExpense}
          onReject={onRejectExpense}
        />
      )}

      {/* Create Expense Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-bold text-[var(--text)] mb-4">Add Expense</h3>

            <div className="space-y-4">
              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-1">Vendor</label>
                <input
                  type="text"
                  value={newExpense.vendorName}
                  onChange={(e) => setNewExpense({ ...newExpense, vendorName: e.target.value })}
                  placeholder="Vendor name"
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-[var(--text-muted)] mb-1">Amount</label>
                  <input
                    type="number"
                    step="0.01"
                    value={newExpense.amount}
                    onChange={(e) => setNewExpense({ ...newExpense, amount: e.target.value })}
                    placeholder="0.00"
                    className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs text-[var(--text-muted)] mb-1">Date</label>
                  <input
                    type="date"
                    value={newExpense.date}
                    onChange={(e) => setNewExpense({ ...newExpense, date: e.target.value })}
                    className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-[var(--text-muted)] mb-1">Category</label>
                  <select
                    value={newExpense.category}
                    onChange={(e) => setNewExpense({ ...newExpense, category: e.target.value })}
                    className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none"
                  >
                    {EXPENSE_CATEGORIES.map((cat) => (
                      <option key={cat.value} value={cat.value}>
                        {cat.icon} {cat.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-[var(--text-muted)] mb-1">
                    Payment Method
                  </label>
                  <select
                    value={newExpense.paymentMethod}
                    onChange={(e) =>
                      setNewExpense({ ...newExpense, paymentMethod: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none"
                  >
                    {PAYMENT_METHODS.map((pm) => (
                      <option key={pm.value} value={pm.value}>
                        {pm.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-1">Description</label>
                <textarea
                  value={newExpense.description}
                  onChange={(e) => setNewExpense({ ...newExpense, description: e.target.value })}
                  placeholder="Description"
                  rows={2}
                  className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)] focus:border-[var(--acid-green)] focus:outline-none resize-none"
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="reimbursable"
                  checked={newExpense.isReimbursable}
                  onChange={(e) =>
                    setNewExpense({ ...newExpense, isReimbursable: e.target.checked })
                  }
                  className="rounded"
                />
                <label htmlFor="reimbursable" className="text-sm text-[var(--text)]">
                  Reimbursable expense
                </label>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 text-sm font-theme-data text-[var(--text-muted)] hover:text-[var(--text)]"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateExpense}
                disabled={!newExpense.vendorName || !newExpense.amount}
                className="px-4 py-2 bg-[var(--acid-green)] text-black rounded text-sm font-theme-data hover:opacity-90 disabled:opacity-50"
              >
                Add Expense
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Stats View Component
function StatsView({ stats }: { stats: ExpenseStats }) {
  return (
    <div className="space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
          <div className="text-xs text-[var(--text-muted)]">Total Expenses</div>
          <div className="text-2xl font-theme-data text-[var(--text)]">{stats.totalExpenses}</div>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
          <div className="text-xs text-[var(--text-muted)]">Total Amount</div>
          <div className="text-2xl font-theme-data text-[var(--acid-green)]">
            ${stats.totalAmount.toLocaleString()}
          </div>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
          <div className="text-xs text-[var(--text-muted)]">Pending Approval</div>
          <div className="text-2xl font-theme-data text-yellow-400">{stats.pendingCount}</div>
          <div className="text-xs text-[var(--text-muted)]">
            ${stats.pendingAmount.toLocaleString()}
          </div>
        </div>
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
          <div className="text-xs text-[var(--text-muted)]">Average Expense</div>
          <div className="text-2xl font-theme-data text-[var(--text)]">
            ${stats.avgExpense.toLocaleString()}
          </div>
        </div>
      </div>

      {/* Category Breakdown */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-bold text-[var(--text)] mb-4">By Category</h3>
        <div className="space-y-2">
          {Object.entries(stats.byCategory)
            .sort(([, a], [, b]) => b - a)
            .map(([category, amount]) => (
              <div key={category} className="flex items-center gap-2">
                <span className="text-lg">
                  {EXPENSE_CATEGORIES.find((c) => c.value === category)?.icon || '📦'}
                </span>
                <span className="flex-1 text-sm text-[var(--text)]">{category}</span>
                <span className="font-theme-data text-sm text-[var(--text)]">
                  ${amount.toLocaleString()}
                </span>
                <div className="w-24 h-2 bg-[var(--border)] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[var(--acid-green)]"
                    style={{ width: `${(amount / stats.totalAmount) * 100}%` }}
                  />
                </div>
              </div>
            ))}
        </div>
      </div>

      {/* Top Vendors */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-bold text-[var(--text)] mb-4">Top Vendors</h3>
        <div className="space-y-2">
          {stats.topVendors.map((vendor, index) => (
            <div key={vendor.vendor} className="flex items-center gap-2">
              <span className="text-xs text-[var(--text-muted)] w-4">{index + 1}.</span>
              <span className="flex-1 text-sm text-[var(--text)]">{vendor.vendor}</span>
              <span className="font-theme-data text-sm text-[var(--text)]">
                ${vendor.total.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// List View Component
function ListView({
  expenses,
  selectedExpenses,
  onToggleSelect,
  onSelectAll,
  getStatusColor,
  getCategoryIcon,
  onApprove,
  onReject,
}: {
  expenses: Expense[];
  selectedExpenses: Set<string>;
  onToggleSelect: (id: string) => void;
  onSelectAll: () => void;
  getStatusColor: (status: string) => string;
  getCategoryIcon: (category: string) => string;
  onApprove?: (id: string) => Promise<void>;
  onReject?: (id: string, reason: string) => Promise<void>;
}) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
      {/* Header */}
      <div className="grid grid-cols-12 gap-4 p-3 bg-[var(--bg)] border-b border-[var(--border)] text-xs font-theme-data text-[var(--text-muted)]">
        <div className="col-span-1">
          <input
            type="checkbox"
            checked={selectedExpenses.size === expenses.length && expenses.length > 0}
            onChange={onSelectAll}
            className="rounded"
          />
        </div>
        <div className="col-span-1">Cat</div>
        <div className="col-span-2">Vendor</div>
        <div className="col-span-2">Date</div>
        <div className="col-span-2 text-right">Amount</div>
        <div className="col-span-2">Status</div>
        <div className="col-span-2 text-right">Actions</div>
      </div>

      {/* Rows */}
      {expenses.length === 0 ? (
        <div className="p-8 text-center text-[var(--text-muted)] font-theme-data text-sm">
          No expenses found. Upload a receipt or add one manually.
        </div>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {expenses.map((expense) => (
            <div
              key={expense.id}
              className={`grid grid-cols-12 gap-4 p-3 hover:bg-[var(--bg)] transition-colors items-center ${
                selectedExpenses.has(expense.id) ? 'bg-[var(--acid-green)]/5' : ''
              }`}
            >
              <div className="col-span-1">
                <input
                  type="checkbox"
                  checked={selectedExpenses.has(expense.id)}
                  onChange={() => onToggleSelect(expense.id)}
                  className="rounded"
                />
              </div>
              <div className="col-span-1 text-lg">{getCategoryIcon(expense.category)}</div>
              <div className="col-span-2">
                <div className="text-sm text-[var(--text)] truncate">{expense.vendorName}</div>
                {expense.description && (
                  <div className="text-xs text-[var(--text-muted)] truncate">
                    {expense.description}
                  </div>
                )}
              </div>
              <div className="col-span-2">
                <div className="text-sm text-[var(--text)]">
                  {new Date(expense.date).toLocaleDateString()}
                </div>
              </div>
              <div className="col-span-2 text-right">
                <div className="font-theme-data text-sm text-[var(--text)]">
                  ${expense.totalAmount.toLocaleString()}
                </div>
                {expense.isReimbursable && (
                  <div className="text-xs text-blue-400">Reimbursable</div>
                )}
              </div>
              <div className="col-span-2">
                <span
                  className={`px-2 py-1 text-xs font-theme-data rounded ${getStatusColor(expense.status)}`}
                >
                  {expense.status}
                </span>
              </div>
              <div className="col-span-2 text-right">
                {expense.status === 'processed' || expense.status === 'categorized' ? (
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={() => onApprove?.(expense.id)}
                      className="px-2 py-1 text-xs font-theme-data bg-green-500/20 text-green-400 rounded hover:bg-green-500/30"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => onReject?.(expense.id, '')}
                      className="px-2 py-1 text-xs font-theme-data bg-red-500/20 text-red-400 rounded hover:bg-red-500/30"
                    >
                      Reject
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Grid View Component
function GridView({
  expenses,
  selectedExpenses,
  onToggleSelect,
  getStatusColor,
  getCategoryIcon,
}: {
  expenses: Expense[];
  selectedExpenses: Set<string>;
  onToggleSelect: (id: string) => void;
  getStatusColor: (status: string) => string;
  getCategoryIcon: (category: string) => string;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {expenses.map((expense) => (
        <div
          key={expense.id}
          className={`bg-[var(--surface)] border border-[var(--border)] rounded p-4 hover:border-[var(--acid-green)]/50 transition-colors cursor-pointer ${
            selectedExpenses.has(expense.id) ? 'border-[var(--acid-green)]' : ''
          }`}
          onClick={() => onToggleSelect(expense.id)}
        >
          <div className="flex items-start justify-between mb-2">
            <span className="text-2xl">{getCategoryIcon(expense.category)}</span>
            <span
              className={`px-2 py-1 text-xs font-theme-data rounded ${getStatusColor(expense.status)}`}
            >
              {expense.status}
            </span>
          </div>
          <div className="font-theme-data text-lg text-[var(--text)] mb-1">
            ${expense.totalAmount.toLocaleString()}
          </div>
          <div className="text-sm text-[var(--text)] truncate">{expense.vendorName}</div>
          <div className="text-xs text-[var(--text-muted)] mt-1">
            {new Date(expense.date).toLocaleDateString()}
          </div>
          {expense.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {expense.tags.slice(0, 3).map((tag) => (
                <span
                  key={tag}
                  className="px-1 py-0.5 text-xs bg-[var(--bg)] rounded text-[var(--text-muted)]"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default ExpenseTracker;
