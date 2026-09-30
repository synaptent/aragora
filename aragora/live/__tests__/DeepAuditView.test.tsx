import { render, screen, fireEvent } from '@testing-library/react';
import { DeepAuditView, DeepAuditToggle } from '@/components/deep-audit';
import type { StreamEvent } from '../src/types/events';

// Mock child components
jest.mock('../src/components/RoleBadge', () => ({
  RoleBadge: ({ role }: { role: string }) => <span data-testid="role-badge">{role}</span>,
}));

jest.mock('../src/components/CitationsPanel', () => ({
  CitationBadge: ({ count }: { count: number }) => (
    <span data-testid="citation-badge">{count}</span>
  ),
}));

// Helper to create mock events
const createEvent = (overrides: Partial<StreamEvent> = {}): StreamEvent => ({
  type: 'agent_message',
  data: {},
  timestamp: Date.now() / 1000,
  round: 1,
  agent: 'claude',
  loop_id: 'test-loop',
  ...overrides,
});

describe('DeepAuditView', () => {
  const defaultProps = { events: [] as StreamEvent[], isActive: true, onToggle: jest.fn() };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('inactive state', () => {
    it('shows activation button when inactive', () => {
      render(<DeepAuditView {...defaultProps} isActive={false} />);

      expect(screen.getByText('Deep Audit Mode')).toBeInTheDocument();
      expect(screen.getByRole('button')).toBeInTheDocument();
    });

    it('calls onToggle when activation button clicked', () => {
      const onToggle = jest.fn();
      render(<DeepAuditView {...defaultProps} isActive={false} onToggle={onToggle} />);

      fireEvent.click(screen.getByRole('button'));

      expect(onToggle).toHaveBeenCalled();
    });
  });

  describe('active state', () => {
    it('renders header with progress', () => {
      render(<DeepAuditView {...defaultProps} />);

      expect(screen.getByText('Deep Audit Mode')).toBeInTheDocument();
      expect(screen.getByText('0/6 rounds complete')).toBeInTheDocument();
    });

    it('shows all 6 audit rounds', () => {
      render(<DeepAuditView {...defaultProps} />);

      expect(screen.getByText(/Round 1: Initial Analysis/)).toBeInTheDocument();
      expect(screen.getByText(/Round 2: Skeptical Review/)).toBeInTheDocument();
      expect(screen.getByText(/Round 3: Lateral Exploration/)).toBeInTheDocument();
      expect(screen.getByText(/Round 4: Devil's Advocacy/)).toBeInTheDocument();
      expect(screen.getByText(/Round 5: Synthesis/)).toBeInTheDocument();
      expect(screen.getByText(/Round 6: Cross-Examination/)).toBeInTheDocument();
    });

    it('shows exit button', () => {
      render(<DeepAuditView {...defaultProps} />);

      expect(screen.getByText('Exit')).toBeInTheDocument();
    });

    it('calls onToggle when exit clicked', () => {
      const onToggle = jest.fn();
      render(<DeepAuditView {...defaultProps} onToggle={onToggle} />);

      fireEvent.click(screen.getByText('Exit'));

      expect(onToggle).toHaveBeenCalled();
    });
  });

  describe('round tracking', () => {
    it('marks rounds as complete based on events', () => {
      const events: StreamEvent[] = [
        createEvent({
          round: 1,
          type: 'agent_message',
          agent: 'claude',
          data: { content: 'Analysis 1' },
        }),
        createEvent({
          round: 2,
          type: 'agent_message',
          agent: 'gpt4',
          data: { content: 'Review 1' },
        }),
        createEvent({
          round: 3,
          type: 'agent_message',
          agent: 'gemini',
          data: { content: 'Exploration' },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('2/6 rounds complete')).toBeInTheDocument();
    });

    it('shows response count for rounds with messages', () => {
      const events: StreamEvent[] = [
        createEvent({ round: 1, type: 'agent_message', agent: 'claude', data: { content: 'A' } }),
        createEvent({ round: 1, type: 'agent_message', agent: 'gpt4', data: { content: 'B' } }),
        createEvent({ round: 1, type: 'agent_message', agent: 'gemini', data: { content: 'C' } }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('3 responses')).toBeInTheDocument();
    });

    it('shows singular response count', () => {
      const events: StreamEvent[] = [
        createEvent({ round: 1, type: 'agent_message', agent: 'claude', data: { content: 'A' } }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('1 response')).toBeInTheDocument();
    });
  });

  describe('round expansion', () => {
    it('expands round when clicked', () => {
      const events: StreamEvent[] = [
        createEvent({
          round: 1,
          type: 'agent_message',
          agent: 'claude',
          data: { content: 'Test content' },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      // Click to expand round 1
      const round1Button = screen.getByText(/Round 1: Initial Analysis/).closest('button');
      fireEvent.click(round1Button!);

      expect(screen.getByText('Test content')).toBeInTheDocument();
    });

    it('collapses round when clicked again', () => {
      const events: StreamEvent[] = [
        createEvent({
          round: 1,
          type: 'agent_message',
          agent: 'claude',
          data: { content: 'Test content' },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      const round1Button = screen.getByText(/Round 1: Initial Analysis/).closest('button');

      // Expand
      fireEvent.click(round1Button!);
      expect(screen.getByText('Test content')).toBeInTheDocument();

      // Collapse
      fireEvent.click(round1Button!);
      expect(screen.queryByText('Test content')).not.toBeInTheDocument();
    });

    it('disables pending round buttons', () => {
      render(<DeepAuditView {...defaultProps} events={[]} />);

      // All buttons should be disabled when no events
      const buttons = screen.getAllByRole('button');
      // Exit button should not be disabled, but round buttons should be
      const roundButtons = buttons.filter((btn) => btn.textContent?.includes('Round'));
      roundButtons.forEach((btn) => {
        expect(btn).toBeDisabled();
      });
    });
  });

  describe('audit_round events', () => {
    it('processes audit_round events with messages', () => {
      const events: StreamEvent[] = [
        createEvent({
          type: 'audit_round',
          round: 1,
          data: {
            round: 1,
            name: 'Initial Analysis',
            cognitive_role: 'analyzer',
            messages: [
              { agent: 'claude', content: 'My analysis', confidence: 0.85 },
              { agent: 'gpt4', content: 'My take', confidence: 0.72 },
            ],
          },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('2 responses')).toBeInTheDocument();
    });
  });

  describe('findings section', () => {
    it('shows findings count when present', () => {
      const events: StreamEvent[] = [
        createEvent({
          type: 'audit_finding',
          data: {
            category: 'unanimous',
            summary: 'All agents agree on this',
            agents_agree: ['claude', 'gpt4'],
            confidence: 0.9,
          },
        }),
        createEvent({
          type: 'audit_finding',
          data: { category: 'risk', summary: 'Potential security issue', severity: 0.8 },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('2 Findings Detected')).toBeInTheDocument();
    });

    it('expands findings when clicked', () => {
      const events: StreamEvent[] = [
        createEvent({
          type: 'audit_finding',
          data: {
            category: 'unanimous',
            summary: 'All agents agree on this point',
            agents_agree: ['claude', 'gpt4'],
          },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      // Click to expand findings
      fireEvent.click(screen.getByText('1 Finding Detected'));

      expect(screen.getByText('All agents agree on this point')).toBeInTheDocument();
      expect(screen.getByText('Unanimous')).toBeInTheDocument();
    });

    it('shows agents who agree and disagree', () => {
      const events: StreamEvent[] = [
        createEvent({
          type: 'audit_finding',
          data: {
            category: 'split',
            summary: 'Split opinion',
            agents_agree: ['claude'],
            agents_disagree: ['gpt4'],
          },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      fireEvent.click(screen.getByText('1 Finding Detected'));

      expect(screen.getByText('Agree: claude')).toBeInTheDocument();
      expect(screen.getByText('Disagree: gpt4')).toBeInTheDocument();
    });
  });

  describe('verdict section', () => {
    it('shows verdict when present', () => {
      const events: StreamEvent[] = [
        createEvent({
          type: 'audit_verdict',
          data: {
            recommendation: 'The proposal is sound with minor adjustments',
            confidence: 0.85,
            unanimous_issues: ['Issue 1', 'Issue 2'],
            split_opinions: ['Opinion 1'],
            risk_areas: ['Risk 1'],
          },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('Final Audit Verdict')).toBeInTheDocument();
      expect(screen.getByText('The proposal is sound with minor adjustments')).toBeInTheDocument();
      expect(screen.getByText('85% confidence')).toBeInTheDocument();
    });

    it('shows unanimous issues, split opinions, and risks', () => {
      const events: StreamEvent[] = [
        createEvent({
          type: 'audit_verdict',
          data: {
            recommendation: 'Recommendation',
            confidence: 0.75,
            unanimous_issues: ['All agree on this'],
            split_opinions: ['Some disagree here'],
            risk_areas: ['Watch out for this'],
          },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('Unanimous Issues (1)')).toBeInTheDocument();
      expect(screen.getByText('Split Opinions (1)')).toBeInTheDocument();
      expect(screen.getByText('Risk Areas (1)')).toBeInTheDocument();
    });
  });

  describe('cross-examination notes', () => {
    it('shows cross-exam notes when present', () => {
      const events: StreamEvent[] = [
        createEvent({
          type: 'audit_cross_exam',
          data: { notes: 'Key questions raised during cross-examination' },
        }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('Cross-Examination Notes')).toBeInTheDocument();
      expect(screen.getByText('Key questions raised during cross-examination')).toBeInTheDocument();
    });
  });

  describe('active round summary', () => {
    it('shows active round panel', () => {
      const events: StreamEvent[] = [
        createEvent({ round: 2, type: 'agent_message', agent: 'claude', data: { content: 'A' } }),
      ];

      render(<DeepAuditView {...defaultProps} events={events} />);

      expect(screen.getByText('Currently: Skeptical Review')).toBeInTheDocument();
      expect(screen.getByText('1 agents have responded in this round')).toBeInTheDocument();
    });
  });
});

describe('DeepAuditToggle', () => {
  it('shows inactive state', () => {
    render(<DeepAuditToggle isActive={false} onToggle={jest.fn()} />);

    expect(screen.getByText('Deep Audit')).toBeInTheDocument();
  });

  it('shows active state', () => {
    render(<DeepAuditToggle isActive={true} onToggle={jest.fn()} />);

    expect(screen.getByText('Deep Audit Active')).toBeInTheDocument();
  });

  it('calls onToggle when clicked', () => {
    const onToggle = jest.fn();
    render(<DeepAuditToggle isActive={false} onToggle={onToggle} />);

    fireEvent.click(screen.getByRole('button'));

    expect(onToggle).toHaveBeenCalled();
  });
});
