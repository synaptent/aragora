'use client';

import { useState } from 'react';

type ReportType = 'profit_loss' | 'balance_sheet' | 'ar_aging' | 'ap_aging' | 'cash_flow';

// Report data types
interface LineItem {
  name: string;
  amount: number;
}

interface AgingBucket {
  label: string;
  amount: number;
  customers: number;
}

interface IncomeExpenseSection {
  items: LineItem[];
  total: number;
}

interface ProfitLossData {
  income: IncomeExpenseSection;
  expenses: IncomeExpenseSection;
  netIncome: number;
}

interface AssetSection {
  total: number;
  current: IncomeExpenseSection;
  fixed: IncomeExpenseSection;
}

interface BalanceSheetData {
  asOf?: string;
  assets: AssetSection;
  liabilities: IncomeExpenseSection;
  equity: IncomeExpenseSection;
}

interface AgingData {
  asOf?: string;
  buckets: AgingBucket[];
  total: number;
}

interface CashFlowData {
  operating: IncomeExpenseSection;
  investing: IncomeExpenseSection;
  financing: IncomeExpenseSection;
  netChange: number;
}

type ReportDataByType = {
  profit_loss: ProfitLossData;
  balance_sheet: BalanceSheetData;
  ar_aging: AgingData;
  ap_aging: AgingData;
  cash_flow: CashFlowData;
};

interface ReportData<T extends ReportType = ReportType> {
  type: T;
  period?: { start: string; end: string };
  data: ReportDataByType[T];
}

interface ReportConfig {
  id: ReportType;
  name: string;
  description: string;
  icon: string;
  requiresDates: boolean;
}

const REPORT_TYPES: ReportConfig[] = [
  {
    id: 'profit_loss',
    name: 'Profit & Loss',
    description: 'Income and expenses for a period',
    icon: '📈',
    requiresDates: true,
  },
  {
    id: 'balance_sheet',
    name: 'Balance Sheet',
    description: 'Assets, liabilities, and equity snapshot',
    icon: '⚖️',
    requiresDates: false,
  },
  {
    id: 'ar_aging',
    name: 'AR Aging',
    description: 'Accounts receivable by age',
    icon: '📊',
    requiresDates: false,
  },
  {
    id: 'ap_aging',
    name: 'AP Aging',
    description: 'Accounts payable by age',
    icon: '📋',
    requiresDates: false,
  },
  {
    id: 'cash_flow',
    name: 'Cash Flow',
    description: 'Cash inflows and outflows',
    icon: '💵',
    requiresDates: true,
  },
];

// Mock report data
const MOCK_PROFIT_LOSS = {
  period: { start: '2025-01-01', end: '2025-01-22' },
  income: {
    total: 125000,
    items: [
      { name: 'Service Revenue', amount: 95000 },
      { name: 'Product Sales', amount: 25000 },
      { name: 'Other Income', amount: 5000 },
    ],
  },
  expenses: {
    total: 78500,
    items: [
      { name: 'Salaries & Wages', amount: 45000 },
      { name: 'Rent & Utilities', amount: 12000 },
      { name: 'Software & Tools', amount: 8500 },
      { name: 'Marketing', amount: 6000 },
      { name: 'Professional Services', amount: 4000 },
      { name: 'Other Expenses', amount: 3000 },
    ],
  },
  netIncome: 46500,
};

const MOCK_BALANCE_SHEET = {
  asOf: '2025-01-22',
  assets: {
    total: 285000,
    current: {
      total: 185000,
      items: [
        { name: 'Cash & Bank', amount: 125000 },
        { name: 'Accounts Receivable', amount: 46270 },
        { name: 'Inventory', amount: 8730 },
        { name: 'Prepaid Expenses', amount: 5000 },
      ],
    },
    fixed: {
      total: 100000,
      items: [
        { name: 'Equipment', amount: 75000 },
        { name: 'Vehicles', amount: 25000 },
      ],
    },
  },
  liabilities: {
    total: 62000,
    items: [
      { name: 'Accounts Payable', amount: 12340 },
      { name: 'Credit Cards', amount: 4660 },
      { name: 'Loan Payable', amount: 45000 },
    ],
  },
  equity: {
    total: 223000,
    items: [
      { name: 'Retained Earnings', amount: 176500 },
      { name: 'Current Year Earnings', amount: 46500 },
    ],
  },
};

const MOCK_AR_AGING = {
  asOf: '2025-01-22',
  total: 46270.5,
  buckets: [
    { label: 'Current', amount: 15420.5, customers: 3 },
    { label: '1-30 Days', amount: 12100.0, customers: 2 },
    { label: '31-60 Days', amount: 8750.0, customers: 1 },
    { label: '61-90 Days', amount: 5000.0, customers: 1 },
    { label: '90+ Days', amount: 5000.0, customers: 1 },
  ],
  customers: [
    {
      name: 'Acme Corporation',
      current: 5420.5,
      '1-30': 5000,
      '31-60': 0,
      '61-90': 5000,
      '90+': 0,
      total: 15420.5,
    },
    {
      name: 'TechStart Inc',
      current: 0,
      '1-30': 0,
      '31-60': 8750,
      '61-90': 0,
      '90+': 0,
      total: 8750.0,
    },
    {
      name: 'Green Energy Solutions',
      current: 10000,
      '1-30': 7100,
      '31-60': 0,
      '61-90': 0,
      '90+': 5000,
      total: 22100.0,
    },
  ],
};

export function ReportGenerator() {
  const [selectedReport, setSelectedReport] = useState<ReportType | null>(null);
  const [dateRange, setDateRange] = useState({
    start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
    end: new Date().toISOString().split('T')[0],
  });
  const [generating, setGenerating] = useState(false);
  const [reportData, setReportData] = useState<ReportData | null>(null);

  const generateReport = async () => {
    if (!selectedReport) return;

    setGenerating(true);
    setReportData(null);

    // Simulate API call
    await new Promise((resolve) => setTimeout(resolve, 1500));

    // Return mock data based on report type
    switch (selectedReport) {
      case 'profit_loss':
        setReportData({ type: 'profit_loss', data: MOCK_PROFIT_LOSS });
        break;
      case 'balance_sheet':
        setReportData({ type: 'balance_sheet', data: MOCK_BALANCE_SHEET });
        break;
      case 'ar_aging':
        setReportData({ type: 'ar_aging', data: MOCK_AR_AGING });
        break;
      case 'ap_aging':
        setReportData({ type: 'ap_aging', data: { ...MOCK_AR_AGING, total: 12340 } });
        break;
      case 'cash_flow':
        setReportData({ type: 'cash_flow', data: MOCK_PROFIT_LOSS });
        break;
    }

    setGenerating(false);
  };

  const config = selectedReport ? REPORT_TYPES.find((r) => r.id === selectedReport) : null;

  return (
    <div className="space-y-6">
      {/* Report Selection */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
          {'>'} SELECT REPORT
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {REPORT_TYPES.map((report) => (
            <button
              key={report.id}
              onClick={() => setSelectedReport(report.id)}
              className={`p-4 text-left border rounded transition-colors ${
                selectedReport === report.id
                  ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                  : 'border-[var(--border)] hover:border-[var(--acid-green)]/30'
              }`}
            >
              <div className="text-2xl mb-2">{report.icon}</div>
              <div className="font-theme-data text-sm text-[var(--text)]">{report.name}</div>
              <div className="text-xs text-[var(--text-muted)] mt-1">{report.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Date Range (if required) */}
      {config?.requiresDates && (
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
            {'>'} DATE RANGE
          </h3>
          <div className="flex items-center gap-4">
            <div>
              <label className="text-xs text-[var(--text-muted)] block mb-1">Start Date</label>
              <input
                type="date"
                value={dateRange.start}
                onChange={(e) => setDateRange({ ...dateRange, start: e.target.value })}
                className="px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)]"
              />
            </div>
            <div>
              <label className="text-xs text-[var(--text-muted)] block mb-1">End Date</label>
              <input
                type="date"
                value={dateRange.end}
                onChange={(e) => setDateRange({ ...dateRange, end: e.target.value })}
                className="px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded font-theme-data text-sm text-[var(--text)]"
              />
            </div>
          </div>
        </div>
      )}

      {/* Generate Button */}
      {selectedReport && (
        <div className="flex justify-end">
          <button
            onClick={generateReport}
            disabled={generating}
            className="px-6 py-3 bg-[var(--acid-green)] text-[var(--bg)] font-theme-data text-sm rounded hover:bg-[var(--acid-green)]/80 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {generating ? (
              <>
                <span className="animate-spin">⏳</span>
                <span>Generating...</span>
              </>
            ) : (
              <>
                <span>Generate Report</span>
                <span>→</span>
              </>
            )}
          </button>
        </div>
      )}

      {/* Report Output */}
      {reportData && (
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
          {/* Report Header */}
          <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
            <div>
              <h3 className="text-lg font-theme-data text-[var(--acid-green)]">{config?.name}</h3>
              <p className="text-xs text-[var(--text-muted)]">
                Generated on {new Date().toLocaleString()}
              </p>
            </div>
            <button
              onClick={() => window.print()}
              className="px-3 py-1 text-xs font-theme-data border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Export PDF
            </button>
          </div>

          {/* Profit & Loss Report */}
          {reportData.type === 'profit_loss' &&
            (() => {
              const plData = reportData.data as ProfitLossData;
              return (
                <div className="p-4 space-y-6">
                  {/* Income Section */}
                  <div>
                    <h4 className="text-sm font-theme-data text-[var(--acid-green)] mb-3">
                      Income
                    </h4>
                    <div className="space-y-2">
                      {plData.income.items.map((item: LineItem) => (
                        <div key={item.name} className="flex justify-between text-sm">
                          <span className="text-[var(--text-muted)]">{item.name}</span>
                          <span className="font-theme-data text-[var(--acid-green)]">
                            ${item.amount.toLocaleString()}
                          </span>
                        </div>
                      ))}
                      <div className="flex justify-between text-sm font-bold pt-2 border-t border-[var(--border)]">
                        <span>Total Income</span>
                        <span className="font-theme-data text-[var(--acid-green)]">
                          ${plData.income.total.toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Expenses Section */}
                  <div>
                    <h4 className="text-sm font-theme-data text-red-400 mb-3">Expenses</h4>
                    <div className="space-y-2">
                      {plData.expenses.items.map((item: LineItem) => (
                        <div key={item.name} className="flex justify-between text-sm">
                          <span className="text-[var(--text-muted)]">{item.name}</span>
                          <span className="font-theme-data text-red-400">
                            ${item.amount.toLocaleString()}
                          </span>
                        </div>
                      ))}
                      <div className="flex justify-between text-sm font-bold pt-2 border-t border-[var(--border)]">
                        <span>Total Expenses</span>
                        <span className="font-theme-data text-red-400">
                          ${plData.expenses.total.toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Net Income */}
                  <div className="pt-4 border-t-2 border-[var(--acid-green)]">
                    <div className="flex justify-between text-lg font-bold">
                      <span>Net Income</span>
                      <span
                        className={`font-theme-data ${plData.netIncome >= 0 ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
                      >
                        ${plData.netIncome.toLocaleString()}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })()}

          {/* Balance Sheet Report */}
          {reportData.type === 'balance_sheet' &&
            (() => {
              const bsData = reportData.data as BalanceSheetData;
              return (
                <div className="p-4 grid grid-cols-2 gap-6">
                  {/* Assets */}
                  <div>
                    <h4 className="text-sm font-theme-data text-[var(--acid-green)] mb-3">
                      Assets
                    </h4>
                    <div className="space-y-4">
                      <div>
                        <h5 className="text-xs text-[var(--text-muted)] mb-2">Current Assets</h5>
                        {bsData.assets.current.items.map((item: LineItem) => (
                          <div key={item.name} className="flex justify-between text-sm py-1">
                            <span className="text-[var(--text-muted)]">{item.name}</span>
                            <span className="font-theme-data">${item.amount.toLocaleString()}</span>
                          </div>
                        ))}
                      </div>
                      <div>
                        <h5 className="text-xs text-[var(--text-muted)] mb-2">Fixed Assets</h5>
                        {bsData.assets.fixed.items.map((item: LineItem) => (
                          <div key={item.name} className="flex justify-between text-sm py-1">
                            <span className="text-[var(--text-muted)]">{item.name}</span>
                            <span className="font-theme-data">${item.amount.toLocaleString()}</span>
                          </div>
                        ))}
                      </div>
                      <div className="flex justify-between text-sm font-bold pt-2 border-t border-[var(--border)]">
                        <span>Total Assets</span>
                        <span className="font-theme-data text-[var(--acid-green)]">
                          ${bsData.assets.total.toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Liabilities & Equity */}
                  <div>
                    <h4 className="text-sm font-theme-data text-red-400 mb-3">
                      Liabilities & Equity
                    </h4>
                    <div className="space-y-4">
                      <div>
                        <h5 className="text-xs text-[var(--text-muted)] mb-2">Liabilities</h5>
                        {bsData.liabilities.items.map((item: LineItem) => (
                          <div key={item.name} className="flex justify-between text-sm py-1">
                            <span className="text-[var(--text-muted)]">{item.name}</span>
                            <span className="font-theme-data">${item.amount.toLocaleString()}</span>
                          </div>
                        ))}
                      </div>
                      <div>
                        <h5 className="text-xs text-[var(--text-muted)] mb-2">Equity</h5>
                        {bsData.equity.items.map((item: LineItem) => (
                          <div key={item.name} className="flex justify-between text-sm py-1">
                            <span className="text-[var(--text-muted)]">{item.name}</span>
                            <span className="font-theme-data">${item.amount.toLocaleString()}</span>
                          </div>
                        ))}
                      </div>
                      <div className="flex justify-between text-sm font-bold pt-2 border-t border-[var(--border)]">
                        <span>Total L&E</span>
                        <span className="font-theme-data">
                          ${(bsData.liabilities.total + bsData.equity.total).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}

          {/* AR/AP Aging Report */}
          {(reportData.type === 'ar_aging' || reportData.type === 'ap_aging') &&
            (() => {
              const agingData = reportData.data as AgingData;
              return (
                <div className="p-4 space-y-4">
                  {/* Summary Buckets */}
                  <div className="grid grid-cols-5 gap-2">
                    {agingData.buckets.map((bucket: AgingBucket) => (
                      <div key={bucket.label} className="p-3 bg-[var(--bg)] rounded text-center">
                        <div className="text-xs text-[var(--text-muted)]">{bucket.label}</div>
                        <div className="text-lg font-theme-data text-[var(--text)]">
                          ${bucket.amount.toLocaleString()}
                        </div>
                        <div className="text-xs text-[var(--text-muted)]">
                          {bucket.customers} accts
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Total */}
                  <div className="flex justify-between items-center p-3 bg-[var(--acid-green)]/10 rounded">
                    <span className="font-theme-data">
                      Total {reportData.type === 'ar_aging' ? 'Receivables' : 'Payables'}
                    </span>
                    <span className="text-xl font-theme-data text-[var(--acid-green)]">
                      ${agingData.total.toLocaleString()}
                    </span>
                  </div>
                </div>
              );
            })()}
        </div>
      )}
    </div>
  );
}

export default ReportGenerator;
