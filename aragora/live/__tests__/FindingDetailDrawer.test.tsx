/**
 * Tests for FindingDetailDrawer component
 *
 * Tests cover:
 * - Rendering when open with finding data
 * - Not rendering when closed
 * - Displaying severity and status badges
 * - Evidence and recommendation sections
 * - Status transition buttons
 * - Comment form functionality
 * - Assignment workflow
 * - Priority selection
 * - Workflow history display
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { FindingDetailDrawer } from '../src/components/FindingDetailDrawer';

// Mock hooks
jest.mock('../src/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

jest.mock('../src/context/AuthContext', () => ({
  useAuth: () => ({ tokens: { access_token: 'test-token' }, user: { id: 'test-user-id' } }),
}));

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockFinding = {
  id: 'finding-001',
  title: 'SQL Injection Vulnerability',
  description: 'User input is not properly sanitized before database queries',
  severity: 'critical' as const,
  status: 'open',
  audit_type: 'security',
  category: 'injection',
  confidence: 0.95,
  evidence_text: 'query = `SELECT * FROM users WHERE id = ${userId}`',
  evidence_location: 'src/database/users.ts:42',
  recommendation: 'Use parameterized queries or prepared statements',
  found_by: 'claude-3-opus',
  document_id: 'doc-001',
  created_at: '2026-01-15T10:00:00Z',
};

const mockWorkflow = {
  finding_id: 'finding-001',
  current_state: 'open',
  assigned_to: null,
  priority: 2,
  due_date: null,
  history: [
    {
      id: 'event-001',
      event_type: 'state_change',
      timestamp: '2026-01-15T10:00:00Z',
      user_id: 'system',
      user_name: 'System',
      from_state: 'new',
      to_state: 'open',
    },
  ],
};

describe('FindingDetailDrawer', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockWorkflow) });
  });

  describe('Visibility', () => {
    it('should not render when isOpen is false', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={false} onClose={jest.fn()} />);

      expect(screen.queryByText('SQL Injection Vulnerability')).not.toBeInTheDocument();
    });

    it('should render when isOpen is true', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText('SQL Injection Vulnerability')).toBeInTheDocument();
    });
  });

  describe('Finding Display', () => {
    it('should display severity badge', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText('CRITICAL')).toBeInTheDocument();
    });

    it('should display status badge', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText('OPEN')).toBeInTheDocument();
    });

    it('should display description', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText(/User input is not properly sanitized/)).toBeInTheDocument();
    });

    it('should display evidence text', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText(/SELECT \* FROM users/)).toBeInTheDocument();
    });

    it('should display evidence location', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText(/src\/database\/users.ts:42/)).toBeInTheDocument();
    });

    it('should display recommendation', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText(/Use parameterized queries/)).toBeInTheDocument();
    });

    it('should display metadata fields', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText('security')).toBeInTheDocument();
      expect(screen.getByText('injection')).toBeInTheDocument();
      expect(screen.getByText('95%')).toBeInTheDocument();
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });
  });

  describe('Close Functionality', () => {
    it('should call onClose when close button is clicked', () => {
      const onClose = jest.fn();
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={onClose} />);

      fireEvent.click(screen.getByText('✕'));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('should call onClose when backdrop is clicked', () => {
      const onClose = jest.fn();
      const { container } = render(
        <FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={onClose} />,
      );

      const backdrop = container.querySelector('.fixed.inset-0');
      if (backdrop) {
        fireEvent.click(backdrop);
        expect(onClose).toHaveBeenCalledTimes(1);
      }
    });
  });

  describe('Status Transitions', () => {
    it('should display valid status transition buttons', async () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      await waitFor(() => {
        // From 'open' state, valid transitions are: triaging, investigating, false_positive, duplicate
        expect(screen.getByText('TRIAGING')).toBeInTheDocument();
        expect(screen.getByText('INVESTIGATING')).toBeInTheDocument();
        expect(screen.getByText('FALSE POSITIVE')).toBeInTheDocument();
        expect(screen.getByText('DUPLICATE')).toBeInTheDocument();
      });
    });

    it('should call API when status transition button is clicked', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockWorkflow) });

      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('TRIAGING')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('TRIAGING'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/audit/findings/finding-001/status',
          expect.objectContaining({
            method: 'PATCH',
            body: JSON.stringify({ status: 'triaging' }),
          }),
        );
      });
    });
  });

  describe('Priority Selection', () => {
    it('should display priority buttons', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText('Critical')).toBeInTheDocument();
      expect(screen.getByText('High')).toBeInTheDocument();
      expect(screen.getByText('Medium')).toBeInTheDocument();
      expect(screen.getByText('Low')).toBeInTheDocument();
      expect(screen.getByText('Lowest')).toBeInTheDocument();
    });

    it('should call API when priority button is clicked', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockWorkflow) });

      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      fireEvent.click(screen.getByText('High'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/audit/findings/finding-001/priority',
          expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ priority: 2 }) }),
        );
      });
    });
  });

  describe('Comment Form', () => {
    it('should display comment textarea', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByPlaceholderText('Add a comment...')).toBeInTheDocument();
    });

    it('should disable add comment button when textarea is empty', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      const button = screen.getByText('Add Comment');
      expect(button).toBeDisabled();
    });

    it('should enable add comment button when textarea has content', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      const textarea = screen.getByPlaceholderText('Add a comment...');
      fireEvent.change(textarea, { target: { value: 'Test comment' } });

      const button = screen.getByText('Add Comment');
      expect(button).not.toBeDisabled();
    });

    it('should call API when comment is submitted', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockWorkflow) });

      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      const textarea = screen.getByPlaceholderText('Add a comment...');
      fireEvent.change(textarea, { target: { value: 'Test comment' } });
      fireEvent.click(screen.getByText('Add Comment'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/audit/findings/finding-001/comments',
          expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ comment: 'Test comment' }),
          }),
        );
      });
    });
  });

  describe('Assignment', () => {
    it('should show Assign button when finding is unassigned', () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      expect(screen.getByText(/Assign →/)).toBeInTheDocument();
    });

    it('should show assignment form when Assign button is clicked', async () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      fireEvent.click(screen.getByText(/Assign →/));

      await waitFor(() => {
        expect(screen.getByPlaceholderText('User ID')).toBeInTheDocument();
      });
    });
  });

  describe('Workflow History', () => {
    it('should fetch workflow data on mount', async () => {
      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/audit/findings/finding-001/history',
          expect.objectContaining({
            headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
          }),
        );
      });
    });

    it('should display workflow history events', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockWorkflow) });

      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText(/Changed status from/)).toBeInTheDocument();
        expect(screen.getByText('new')).toBeInTheDocument();
        expect(screen.getByText('open')).toBeInTheDocument();
      });
    });

    it('should show empty state when no history', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ ...mockWorkflow, history: [] }),
      });

      render(<FindingDetailDrawer finding={mockFinding} isOpen={true} onClose={jest.fn()} />);

      await waitFor(() => {
        expect(screen.getByText('No activity yet')).toBeInTheDocument();
      });
    });
  });

  describe('Different Severity Levels', () => {
    const severities = ['critical', 'high', 'medium', 'low', 'info'] as const;

    severities.forEach((severity) => {
      it(`should display ${severity} severity correctly`, () => {
        render(
          <FindingDetailDrawer
            finding={{ ...mockFinding, severity }}
            isOpen={true}
            onClose={jest.fn()}
          />,
        );

        expect(screen.getByText(severity.toUpperCase())).toBeInTheDocument();
      });
    });
  });
});
