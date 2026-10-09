/**
 * AP Automation Namespace API
 *
 * Provides Accounts Payable automation:
 * - Invoice management
 * - Payment optimization
 * - Cash flow forecasting
 * - Early payment discount detection
 */

/**
 * Payment priority levels.
 */
export type PaymentPriority = 'critical' | 'high' | 'normal' | 'low' | 'hold';

/**
 * Payment method types.
 */
export type APPaymentMethod = 'ach' | 'wire' | 'check' | 'credit_card';

/**
 * Invoice status.
 */
export type APInvoiceStatus = 'unpaid' | 'partial' | 'paid' | 'overdue';

/**
 * AP Invoice.
 */
export interface APInvoice {
  id: string;
  vendor_id: string;
  vendor_name: string;
  invoice_number?: string;
  invoice_date?: string;
  due_date?: string;
  total_amount: number;
  amount_paid: number;
  balance_due: number;
  payment_terms: string;
  early_pay_discount?: number;
  discount_deadline?: string;
  priority?: PaymentPriority;
  preferred_payment_method?: APPaymentMethod;
  status: APInvoiceStatus;
  notes?: string;
  created_at: string;
  updated_at?: string;
}

/**
 * Add invoice request.
 */
export interface AddAPInvoiceRequest {
  vendor_id: string;
  vendor_name: string;
  invoice_number?: string;
  invoice_date?: string;
  due_date: string;
  total_amount: number;
  payment_terms?: string;
  early_pay_discount?: number;
  discount_deadline?: string;
  priority?: PaymentPriority;
  preferred_payment_method?: APPaymentMethod;
  notes?: string;
}

/**
 * Record payment request.
 */
export interface RecordAPPaymentRequest {
  amount: number;
  payment_date?: string;
  payment_method?: APPaymentMethod;
  reference_number?: string;
  notes?: string;
}

/**
 * List invoices parameters.
 */
export interface ListAPInvoicesParams {
  limit?: number;
  offset?: number;
  status?: APInvoiceStatus;
  vendor_id?: string;
  priority?: PaymentPriority;
  due_before?: string;
  due_after?: string;
}

/**
 * Optimize payments request.
 */
export interface OptimizePaymentsRequest {
  available_cash?: number;
  target_date?: string;
  prioritize_discounts?: boolean;
  include_vendors?: string[];
  exclude_vendors?: string[];
}

/**
 * Payment schedule entry.
 */
export interface PaymentScheduleEntry {
  invoice_id: string;
  vendor_name: string;
  amount: number;
  scheduled_date: string;
  payment_method: APPaymentMethod;
  discount_captured?: number;
  priority: PaymentPriority;
}

/**
 * Optimized payment schedule.
 */
export interface PaymentSchedule {
  entries: PaymentScheduleEntry[];
  total_amount: number;
  total_discounts_captured: number;
  cash_required: number;
  generated_at: string;
}

/**
 * Batch payment request.
 */
export interface BatchPaymentRequest {
  invoice_ids: string[];
  payment_date?: string;
  payment_method?: APPaymentMethod;
  notes?: string;
}

/**
 * Batch payment result.
 */
export interface BatchPayment {
  id: string;
  invoice_count: number;
  total_amount: number;
  payment_method: APPaymentMethod;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  created_at: string;
  completed_at?: string;
  payments: Array<{
    invoice_id: string;
    amount: number;
    status: string;
  }>;
}

/**
 * Cash flow forecast entry.
 */
export interface CashFlowEntry {
  date: string;
  inflows: number;
  outflows: number;
  net: number;
  running_balance: number;
}

/**
 * Cash flow forecast.
 */
export interface CashFlowForecast {
  start_date: string;
  end_date: string;
  starting_balance: number;
  entries: CashFlowEntry[];
  total_inflows: number;
  total_outflows: number;
  ending_balance: number;
  generated_at: string;
}

/**
 * Discount opportunity.
 */
export interface DiscountOpportunity {
  invoice_id: string;
  vendor_name: string;
  invoice_amount: number;
  discount_percent: number;
  discount_amount: number;
  deadline: string;
  days_remaining: number;
  annualized_return: number;
}

/**
 * Client interface for AP automation operations.
 */
interface APAutomationClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * AP Automation API namespace.
 *
 * Provides methods for Accounts Payable automation:
 * - Manage vendor invoices
 * - Optimize payment timing
 * - Forecast cash flow
 * - Capture early payment discounts
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Add an invoice
 * const invoice = await client.apAutomation.addInvoice({
 *   vendor_id: 'vendor_123',
 *   vendor_name: 'Acme Corp',
 *   total_amount: 5000,
 *   due_date: '2025-02-15',
 * });
 *
 * // Get payment optimization
 * const schedule = await client.apAutomation.optimizePayments({
 *   available_cash: 10000,
 *   prioritize_discounts: true,
 * });
 * ```
 */
export class APAutomationAPI {
  constructor(private client: APAutomationClientInterface) {}

  /**
   * Add a new AP invoice.
   */
  async addInvoice(
    request: AddAPInvoiceRequest
  ): Promise<{ invoice: APInvoice; message: string }> {
    return this.client.request('POST', '/api/v1/accounting/ap/invoices', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * List AP invoices with filtering.
   */
  async listInvoices(
    params?: ListAPInvoicesParams
  ): Promise<{ invoices: APInvoice[]; total: number; limit: number; offset: number }> {
    return this.client.request('GET', '/api/v1/accounting/ap/invoices', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get a specific AP invoice.
   */
  async getInvoice(invoiceId: string): Promise<{ invoice: APInvoice }> {
    return this.client.request('GET', `/api/v1/accounting/ap/invoices/${invoiceId}`);
  }

  /**
   * Record a payment against an invoice.
   */
  async recordPayment(
    invoiceId: string,
    request: RecordAPPaymentRequest
  ): Promise<{ invoice: APInvoice; message: string }> {
    return this.client.request('POST', `/api/v1/accounting/ap/invoices/${invoiceId}/payment`, {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Optimize payment schedule to maximize discounts and manage cash flow.
   */
  async optimizePayments(
    request?: OptimizePaymentsRequest
  ): Promise<{ schedule: PaymentSchedule }> {
    return this.client.request('POST', '/api/v1/accounting/ap/optimize', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Create a batch payment for multiple invoices.
   */
  async createBatchPayment(request: BatchPaymentRequest): Promise<{ batch: BatchPayment }> {
    return this.client.request('POST', '/api/v1/accounting/ap/batch', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get cash flow forecast.
   */
  async getForecast(daysAhead?: number): Promise<{ forecast: CashFlowForecast }> {
    return this.client.request('GET', '/api/v1/accounting/ap/forecast', {
      params: daysAhead ? { days_ahead: daysAhead } : undefined,
    });
  }

  /**
   * Get early payment discount opportunities.
   */
  async getDiscountOpportunities(): Promise<{ opportunities: DiscountOpportunity[] }> {
    return this.client.request('GET', '/api/v1/accounting/ap/discounts');
  }

  // ===========================================================================
  // AP Shortcut Routes
  // ===========================================================================

  /**
   * List AP invoices (shortcut route).
   */
  async listAPInvoices(
    params?: ListAPInvoicesParams
  ): Promise<{ invoices: APInvoice[]; total: number }> {
    return this.client.request('GET', '/api/v1/ap/invoices', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Optimize AP payments (shortcut route).
   */
  async optimizeAP(
    request?: OptimizePaymentsRequest
  ): Promise<{ schedule: PaymentSchedule }> {
    return this.client.request('POST', '/api/v1/ap/optimize', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Create batch AP payment (shortcut route).
   */
  async createAPBatchPayment(
    request: BatchPaymentRequest
  ): Promise<{ batch: BatchPayment }> {
    return this.client.request('POST', '/api/v1/ap/batch-payments', {
      json: request as unknown as Record<string, unknown>,
    });
  }

  /**
   * Get AP cash flow forecast (shortcut route).
   */
  async getAPCashFlow(params?: { days?: number }): Promise<{ forecast: CashFlowForecast }> {
    return this.client.request('GET', '/api/v1/ap/cash-flow', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get AP discount opportunities (shortcut route).
   */
  async getAPDiscountOpportunities(): Promise<{ opportunities: DiscountOpportunity[] }> {
    return this.client.request('GET', '/api/v1/ap/discount-opportunities');
  }
}
