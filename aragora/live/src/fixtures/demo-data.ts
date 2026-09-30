/**
 * Centralized demo/mock data for frontend components.
 *
 * Used when:
 * - User is not authenticated
 * - API endpoints are unavailable
 * - Running in demo mode
 *
 * This centralizes all demo data to make it easier to maintain
 * and ensures consistent demo experiences across the application.
 */

// =============================================================================
// Accounting Demo Data
// =============================================================================

export interface DemoCompanyInfo {
  name: string;
  legalName: string;
  country: string;
  email: string;
}

export interface DemoDashboardStats {
  receivables: number;
  payables: number;
  revenue: number;
  expenses: number;
  netIncome: number;
  openInvoices: number;
  overdueInvoices: number;
}

export interface DemoCustomer {
  id: string;
  displayName: string;
  companyName: string;
  email: string;
  balance: number;
  active: boolean;
}

export interface DemoTransaction {
  id: string;
  type: string;
  docNumber: string;
  txnDate: string;
  dueDate?: string;
  totalAmount: number;
  balance: number;
  customerName?: string;
  vendorName?: string;
  status: string;
}

export const DEMO_COMPANY: DemoCompanyInfo = {
  name: 'Demo Company',
  legalName: 'Demo Company LLC',
  country: 'US',
  email: 'accounting@demo.com',
};

export const DEMO_DASHBOARD_STATS: DemoDashboardStats = {
  receivables: 46270.5,
  payables: 12340.0,
  revenue: 125000.0,
  expenses: 78500.0,
  netIncome: 46500.0,
  openInvoices: 8,
  overdueInvoices: 2,
};

export const DEMO_CUSTOMERS: DemoCustomer[] = [
  {
    id: '1',
    displayName: 'Acme Corporation',
    companyName: 'Acme Corp',
    email: 'billing@acme.com',
    balance: 15420.5,
    active: true,
  },
  {
    id: '2',
    displayName: 'TechStart Inc',
    companyName: 'TechStart',
    email: 'ap@techstart.io',
    balance: 8750.0,
    active: true,
  },
  {
    id: '3',
    displayName: 'Green Energy Solutions',
    companyName: 'Green Energy',
    email: 'finance@greenenergy.com',
    balance: 22100.0,
    active: true,
  },
  {
    id: '4',
    displayName: 'Metro Retail Group',
    companyName: 'Metro Retail',
    email: 'payments@metroretail.com',
    balance: 0,
    active: true,
  },
];

export const DEMO_TRANSACTIONS: DemoTransaction[] = [
  {
    id: '1001',
    type: 'Invoice',
    docNumber: 'INV-1001',
    txnDate: '2025-01-17',
    dueDate: '2025-02-16',
    totalAmount: 5250.0,
    balance: 5250.0,
    customerName: 'Acme Corporation',
    status: 'Open',
  },
  {
    id: '1002',
    type: 'Invoice',
    docNumber: 'INV-1002',
    txnDate: '2025-01-10',
    dueDate: '2025-02-09',
    totalAmount: 3800.0,
    balance: 0,
    customerName: 'TechStart Inc',
    status: 'Paid',
  },
  {
    id: '1003',
    type: 'Invoice',
    docNumber: 'INV-1003',
    txnDate: '2025-01-05',
    dueDate: '2025-01-20',
    totalAmount: 8750.0,
    balance: 8750.0,
    customerName: 'TechStart Inc',
    status: 'Overdue',
  },
  {
    id: '2001',
    type: 'Expense',
    docNumber: 'EXP-2001',
    txnDate: '2025-01-19',
    totalAmount: 1250.0,
    balance: 0,
    vendorName: 'Office Supplies Co',
    status: 'Paid',
  },
  {
    id: '2002',
    type: 'Expense',
    docNumber: 'EXP-2002',
    txnDate: '2025-01-15',
    totalAmount: 4500.0,
    balance: 0,
    vendorName: 'Cloud Services Inc',
    status: 'Paid',
  },
];

// =============================================================================
// Queue Monitoring Demo Data
// =============================================================================

export interface DemoQueueStats {
  total: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  avgProcessingTime: number;
  throughput: number;
}

export interface DemoQueueJob {
  id: string;
  type: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  priority: 'low' | 'normal' | 'high' | 'urgent';
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface DemoQueueWorker {
  id: string;
  name: string;
  status: 'idle' | 'busy' | 'stopped';
  currentJob?: string;
  processedJobs: number;
  uptime: number;
}

export const DEMO_QUEUE_STATS: DemoQueueStats = {
  total: 1547,
  pending: 23,
  processing: 5,
  completed: 1498,
  failed: 21,
  avgProcessingTime: 2.34,
  throughput: 142.5,
};

export const DEMO_QUEUE_JOBS: DemoQueueJob[] = [
  {
    id: 'job-001',
    type: 'debate',
    status: 'processing',
    priority: 'high',
    createdAt: '2025-01-20T10:30:00Z',
    startedAt: '2025-01-20T10:30:05Z',
    metadata: { agents: 3 },
  },
  {
    id: 'job-002',
    type: 'gauntlet',
    status: 'pending',
    priority: 'normal',
    createdAt: '2025-01-20T10:29:00Z',
  },
  {
    id: 'job-003',
    type: 'workflow',
    status: 'completed',
    priority: 'normal',
    createdAt: '2025-01-20T10:25:00Z',
    startedAt: '2025-01-20T10:25:02Z',
    completedAt: '2025-01-20T10:27:45Z',
  },
  {
    id: 'job-004',
    type: 'debate',
    status: 'failed',
    priority: 'low',
    createdAt: '2025-01-20T10:20:00Z',
    startedAt: '2025-01-20T10:20:01Z',
    error: 'Agent timeout',
  },
  {
    id: 'job-005',
    type: 'analysis',
    status: 'pending',
    priority: 'urgent',
    createdAt: '2025-01-20T10:35:00Z',
  },
];

export const DEMO_QUEUE_WORKERS: DemoQueueWorker[] = [
  {
    id: 'worker-1',
    name: 'debate-worker-1',
    status: 'busy',
    currentJob: 'job-001',
    processedJobs: 523,
    uptime: 86400,
  },
  { id: 'worker-2', name: 'debate-worker-2', status: 'idle', processedJobs: 487, uptime: 86400 },
  {
    id: 'worker-3',
    name: 'gauntlet-worker-1',
    status: 'busy',
    currentJob: 'job-006',
    processedJobs: 312,
    uptime: 43200,
  },
  { id: 'worker-4', name: 'workflow-worker-1', status: 'stopped', processedJobs: 156, uptime: 0 },
];

// =============================================================================
// Integration Status Demo Data
// =============================================================================

export type IntegrationType =
  'slack' | 'discord' | 'teams' | 'email' | 'telegram' | 'whatsapp' | 'webhook' | 'matrix';

export interface DemoIntegrationStatus {
  type: IntegrationType;
  enabled: boolean;
  lastActivity?: string;
  messagesSent: number;
  errors: number;
  status: 'connected' | 'degraded' | 'disconnected' | 'not_configured';
}

export const DEMO_INTEGRATIONS: DemoIntegrationStatus[] = [
  {
    type: 'slack',
    enabled: true,
    lastActivity: '2025-01-20T10:30:00Z',
    messagesSent: 1247,
    errors: 3,
    status: 'connected',
  },
  { type: 'discord', enabled: false, messagesSent: 0, errors: 0, status: 'not_configured' },
  {
    type: 'teams',
    enabled: true,
    lastActivity: '2025-01-20T09:45:00Z',
    messagesSent: 523,
    errors: 0,
    status: 'connected',
  },
  {
    type: 'email',
    enabled: true,
    lastActivity: '2025-01-20T10:15:00Z',
    messagesSent: 89,
    errors: 2,
    status: 'degraded',
  },
  { type: 'telegram', enabled: false, messagesSent: 0, errors: 0, status: 'not_configured' },
  { type: 'whatsapp', enabled: false, messagesSent: 0, errors: 0, status: 'not_configured' },
  {
    type: 'webhook',
    enabled: true,
    lastActivity: '2025-01-20T10:28:00Z',
    messagesSent: 2156,
    errors: 12,
    status: 'connected',
  },
  { type: 'matrix', enabled: false, messagesSent: 0, errors: 0, status: 'not_configured' },
];

// =============================================================================
// Workflow Templates Demo Data
// =============================================================================

export interface DemoWorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  complexity: 'simple' | 'medium' | 'complex';
  estimatedDuration: string;
  tags: string[];
}

export const DEMO_WORKFLOW_TEMPLATES: DemoWorkflowTemplate[] = [
  {
    id: 'tpl-approval-chain',
    name: 'Multi-Level Approval Chain',
    description: 'Sequential approval workflow with escalation',
    category: 'Approval',
    complexity: 'medium',
    estimatedDuration: '1-3 days',
    tags: ['approval', 'governance', 'compliance'],
  },
  {
    id: 'tpl-code-review',
    name: 'AI Code Review Pipeline',
    description: 'Automated code review with multiple agents',
    category: 'Development',
    complexity: 'complex',
    estimatedDuration: '10-30 minutes',
    tags: ['code', 'review', 'development'],
  },
  {
    id: 'tpl-research-synthesis',
    name: 'Research Synthesis',
    description: 'Gather and synthesize research from multiple sources',
    category: 'Research',
    complexity: 'medium',
    estimatedDuration: '15-45 minutes',
    tags: ['research', 'analysis', 'synthesis'],
  },
  {
    id: 'tpl-incident-response',
    name: 'Incident Response',
    description: 'Automated incident triage and response coordination',
    category: 'Operations',
    complexity: 'complex',
    estimatedDuration: 'Real-time',
    tags: ['incident', 'operations', 'alerts'],
  },
];

// =============================================================================
// Knowledge Explorer Demo Data
// =============================================================================

export interface DemoKnowledgeFact {
  id: string;
  statement: string;
  confidence: number;
  source: string;
  domain: string;
  createdAt: string;
  validatedAt?: string;
}

export interface DemoReasoningPattern {
  id: string;
  name: string;
  description: string;
  usageCount: number;
  successRate: number;
}

export const DEMO_KNOWLEDGE_FACTS: DemoKnowledgeFact[] = [
  {
    id: 'fact-1',
    statement: 'Circuit breakers prevent cascade failures',
    confidence: 0.95,
    source: 'system-analysis',
    domain: 'resilience',
    createdAt: '2025-01-15T00:00:00Z',
    validatedAt: '2025-01-18T00:00:00Z',
  },
  {
    id: 'fact-2',
    statement: 'Consensus requires supermajority for stability',
    confidence: 0.88,
    source: 'debate-outcome',
    domain: 'governance',
    createdAt: '2025-01-16T00:00:00Z',
  },
  {
    id: 'fact-3',
    statement: 'Rate limiting improves fairness under load',
    confidence: 0.92,
    source: 'experiment',
    domain: 'performance',
    createdAt: '2025-01-17T00:00:00Z',
    validatedAt: '2025-01-19T00:00:00Z',
  },
];

export const DEMO_REASONING_PATTERNS: DemoReasoningPattern[] = [
  {
    id: 'pattern-1',
    name: 'Convergent Synthesis',
    description: 'Find common ground across opposing views',
    usageCount: 147,
    successRate: 0.89,
  },
  {
    id: 'pattern-2',
    name: 'Risk-Weighted Decision',
    description: 'Balance upside against downside risks',
    usageCount: 89,
    successRate: 0.92,
  },
  {
    id: 'pattern-3',
    name: 'Evidence Triangulation',
    description: 'Validate claims with multiple sources',
    usageCount: 234,
    successRate: 0.85,
  },
];

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Check if we should show demo data based on authentication state.
 */
export function shouldShowDemoData(isAuthenticated: boolean, apiError?: boolean): boolean {
  return !isAuthenticated || apiError === true;
}

/**
 * Format currency for demo data display.
 */
export function formatDemoCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
}
