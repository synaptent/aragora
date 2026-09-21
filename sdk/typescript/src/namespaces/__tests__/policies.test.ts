/**
 * Policies Namespace Tests
 *
 * Comprehensive tests for the policies namespace API including:
 * - Policy CRUD operations
 * - Policy enable/disable
 * - Violation management
 * - Compliance summary
 * - Policy validation
 */

import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { PoliciesAPI } from '../policies';

interface MockClient {
  request: Mock;
}

describe('PoliciesAPI Namespace', () => {
  let api: PoliciesAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
    };
    api = new PoliciesAPI(mockClient as any);
  });

  // ===========================================================================
  // Policy CRUD
  // ===========================================================================

  describe('Policy CRUD', () => {
    it('should list policies', async () => {
      const mockPolicies = {
        policies: [
          { id: 'p1', name: 'Content Filter', type: 'content_filter', enabled: true },
          { id: 'p2', name: 'Rate Limit', type: 'rate_limit', enabled: true },
        ],
        total: 2,
      };
      mockClient.request.mockResolvedValue(mockPolicies);

      const result = await api.list();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/policies', { params: undefined });
      expect(result.policies).toHaveLength(2);
    });

    it('should list policies with filters', async () => {
      const mockPolicies = {
        policies: [{ id: 'p1', name: 'Budget Alert', type: 'budget', severity: 'high' }],
        total: 1,
      };
      mockClient.request.mockResolvedValue(mockPolicies);

      const result = await api.list({ type: 'budget', severity: 'high', enabled: true });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/policies', {
        params: { type: 'budget', severity: 'high', enabled: true },
      });
      expect(result.policies).toHaveLength(1);
    });

    it('should get policy by ID', async () => {
      const mockPolicy = {
        id: 'p1',
        name: 'Content Filter',
        description: 'Filters inappropriate content',
        type: 'content_filter',
        severity: 'high',
        enabled: true,
        rules: [
          { id: 'r1', field: 'content', operator: 'contains', value: 'forbidden' },
        ],
        actions: ['block', 'notify'],
      };
      mockClient.request.mockResolvedValue(mockPolicy);

      const result = await api.get('p1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/policies/p1');
      expect(result.name).toBe('Content Filter');
      expect(result.rules).toHaveLength(1);
    });

    it('should create policy', async () => {
      const mockPolicy = {
        id: 'p_new',
        name: 'Budget Alert',
        description: 'Alert when budget exceeded',
        type: 'budget',
        severity: 'high',
        enabled: true,
        rules: [{ id: 'r1', field: 'monthly_spend', operator: 'gte', value: 1000 }],
        actions: ['warn', 'notify'],
      };
      mockClient.request.mockResolvedValue(mockPolicy);

      const result = await api.create({
        name: 'Budget Alert',
        description: 'Alert when budget exceeded',
        type: 'budget',
        severity: 'high',
        rules: [{ field: 'monthly_spend', operator: 'gte', value: 1000 }],
        actions: ['warn', 'notify'],
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/policies', {
        json: {
          name: 'Budget Alert',
          description: 'Alert when budget exceeded',
          type: 'budget',
          severity: 'high',
          rules: [{ field: 'monthly_spend', operator: 'gte', value: 1000 }],
          actions: ['warn', 'notify'],
        },
      });
      expect(result.id).toBe('p_new');
    });

    it('should update policy', async () => {
      const mockPolicy = {
        id: 'p1',
        name: 'Updated Policy',
        severity: 'critical',
      };
      mockClient.request.mockResolvedValue(mockPolicy);

      const result = await api.update('p1', {
        name: 'Updated Policy',
        severity: 'critical',
      });

      expect(mockClient.request).toHaveBeenCalledWith('PATCH', '/api/policies/p1', {
        json: { name: 'Updated Policy', severity: 'critical' },
      });
      expect(result.name).toBe('Updated Policy');
    });

    it('should delete policy', async () => {
      mockClient.request.mockResolvedValue({ success: true });

      const result = await api.delete('p1');

      expect(mockClient.request).toHaveBeenCalledWith('DELETE', '/api/policies/p1');
      expect(result.success).toBe(true);
    });
  });

  // ===========================================================================
  // Policy Enable/Disable
  // ===========================================================================

  describe('Policy Enable/Disable', () => {
    it('should toggle policy', async () => {
      mockClient.request.mockResolvedValue({ enabled: false });

      const result = await api.toggle('p1');

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/policies/p1/toggle');
      expect(result.enabled).toBe(false);
    });

  });

  // ===========================================================================
  // Violation Management
  // ===========================================================================

  describe('Violation Management', () => {
    it('should get violations for policy', async () => {
      const mockViolations = {
        violations: [
          {
            id: 'v1',
            policy_id: 'p1',
            policy_name: 'Content Filter',
            severity: 'high',
            rule_id: 'r1',
            rule_field: 'content',
            actual_value: 'contains forbidden word',
            expected: 'not contains forbidden',
            action_taken: 'block',
            occurred_at: '2024-01-20T10:00:00Z',
          },
        ],
        total: 1,
      };
      mockClient.request.mockResolvedValue(mockViolations);

      const result = await api.getViolations('p1');

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/policies/p1/violations', {
        params: undefined,
      });
      expect(result.violations).toHaveLength(1);
    });

    it('should get violations with filters', async () => {
      const mockViolations = { violations: [], total: 0 };
      mockClient.request.mockResolvedValue(mockViolations);

      await api.getViolations('p1', {
        resolved: false,
        severity: 'critical',
        since: '2024-01-01',
      });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/policies/p1/violations', {
        params: { resolved: false, severity: 'critical', since: '2024-01-01' },
      });
    });

    it('should get all violations', async () => {
      const mockViolations = {
        violations: [
          { id: 'v1', policy_id: 'p1', severity: 'high' },
          { id: 'v2', policy_id: 'p2', severity: 'medium' },
        ],
        total: 2,
      };
      mockClient.request.mockResolvedValue(mockViolations);

      const result = await api.getAllViolations();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/policies/violations', {
        params: undefined,
      });
      expect(result.violations).toHaveLength(2);
    });

    it('should get all violations with filters', async () => {
      const mockViolations = { violations: [], total: 0 };
      mockClient.request.mockResolvedValue(mockViolations);

      await api.getAllViolations({
        policy_type: 'budget',
        severity: 'critical',
        resolved: false,
        limit: 50,
      });

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/policies/violations', {
        params: { policy_type: 'budget', severity: 'critical', resolved: false, limit: 50 },
      });
    });

    it('should resolve violation', async () => {
      const mockViolation = {
        id: 'v1',
        policy_id: 'p1',
        resolved_at: '2024-01-20T11:00:00Z',
        resolved_by: 'admin1',
        resolution_notes: 'False positive',
      };
      mockClient.request.mockResolvedValue(mockViolation);

      const result = await api.resolveViolation('v1', { notes: 'False positive' });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/policies/violations/v1/resolve', {
        json: { notes: 'False positive' },
      });
      expect(result.resolution_notes).toBe('False positive');
    });
  });

  // ===========================================================================
  // Compliance Summary
  // ===========================================================================

  describe('Compliance Summary', () => {
    it('should get compliance summary', async () => {
      const mockSummary = {
        total_policies: 15,
        enabled_policies: 12,
        violations_today: 5,
        violations_this_week: 23,
        violation_trend: 'decreasing',
        compliance_score: 92.5,
        by_severity: {
          low: 10,
          medium: 8,
          high: 4,
          critical: 1,
        },
        by_type: {
          content_filter: 5,
          rate_limit: 3,
          budget: 2,
          access_control: 3,
          data_retention: 2,
        },
        last_updated: '2024-01-20T10:00:00Z',
      };
      mockClient.request.mockResolvedValue(mockSummary);

      const result = await api.getComplianceSummary();

      expect(mockClient.request).toHaveBeenCalledWith('GET', '/api/compliance/summary');
      expect(result.compliance_score).toBe(92.5);
      expect(result.violation_trend).toBe('decreasing');
    });
  });

  // ===========================================================================
  // Policy Validation
  // ===========================================================================

  describe('Policy Validation', () => {
    it('should validate valid policy', async () => {
      mockClient.request.mockResolvedValue({ valid: true });

      const result = await api.validate({
        name: 'Test Policy',
        description: 'Test',
        type: 'budget',
        severity: 'medium',
        rules: [{ field: 'amount', operator: 'lte', value: 1000 }],
        actions: ['warn'],
      });

      expect(mockClient.request).toHaveBeenCalledWith('POST', '/api/policies/validate', {
        json: {
          name: 'Test Policy',
          description: 'Test',
          type: 'budget',
          severity: 'medium',
          rules: [{ field: 'amount', operator: 'lte', value: 1000 }],
          actions: ['warn'],
        },
      });
      expect(result.valid).toBe(true);
    });

    it('should return validation errors', async () => {
      mockClient.request.mockResolvedValue({
        valid: false,
        errors: ['Rule field "invalid_field" does not exist', 'At least one action is required'],
      });

      const result = await api.validate({
        name: 'Invalid Policy',
        description: 'Test',
        type: 'custom',
        severity: 'low',
        rules: [{ field: 'invalid_field', operator: 'eq', value: 'test' }],
        actions: [],
      });

      expect(result.valid).toBe(false);
      expect(result.errors).toHaveLength(2);
    });
  });
});
