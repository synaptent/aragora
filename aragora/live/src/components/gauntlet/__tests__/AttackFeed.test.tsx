import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttackFeed } from '../AttackFeed';

// Mock the hook
const mockReconnect = jest.fn();
const mockHookReturn = {
  status: 'connecting' as const,
  error: null as string | null,
  phase: 'init',
  progress: 0,
  agents: new Map() as Map<
    string,
    { name: string; status: string; attackCount: number; probeCount: number }
  >,
  findings: [] as Array<{
    finding_id: string;
    severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
    category: string;
    title: string;
    description: string;
    source: string;
  }>,
  events: [] as Array<{
    type: string;
    data: Record<string, unknown>;
    timestamp: number;
    seq: number;
  }>,
  verdict: null as null | {
    verdict: string;
    confidence: number;
    riskScore: number;
    robustnessScore: number;
    findings: { critical: number; high: number; medium: number; low: number; total: number };
  },
  elapsedSeconds: 0,
  reconnect: mockReconnect,
  isConnected: false,
  inputType: '',
  inputSummary: '',
  reconnectAttempt: 0,
};

jest.mock('@/hooks/useGauntletWebSocket', () => ({ useGauntletWebSocket: () => mockHookReturn }));

describe('AttackFeed', () => {
  const defaultProps = { gauntletId: 'gauntlet-456', wsUrl: 'wss://test.com/ws' };

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset mock values
    mockHookReturn.status = 'connecting';
    mockHookReturn.error = null;
    mockHookReturn.phase = 'init';
    mockHookReturn.progress = 0;
    mockHookReturn.agents = new Map();
    mockHookReturn.findings = [];
    mockHookReturn.events = [];
    mockHookReturn.verdict = null;
    mockHookReturn.elapsedSeconds = 0;
  });

  describe('initial render', () => {
    it('renders the feed header', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText(/LIVE ATTACK FEED/)).toBeInTheDocument();
    });

    it('shows connecting status', () => {
      render(<AttackFeed {...defaultProps} />);

      // Multiple elements may contain "connecting" text
      const connectingElements = screen.getAllByText(/connecting/i);
      expect(connectingElements.length).toBeGreaterThan(0);
    });

    it('shows connecting message when no events', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('Connecting to stress test...')).toBeInTheDocument();
    });

    it('shows gauntlet ID in footer', () => {
      render(<AttackFeed {...defaultProps} />);

      // Shows last 8 characters of the ID
      expect(screen.getByText(/ID:/)).toBeInTheDocument();
    });
  });

  describe('streaming state', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.phase = 'attack';
      mockHookReturn.progress = 0.5;
      mockHookReturn.elapsedSeconds = 90;
    });

    it('shows streaming status', () => {
      render(<AttackFeed {...defaultProps} />);

      // Multiple elements may contain "streaming" text
      const streamingElements = screen.getAllByText(/streaming/i);
      expect(streamingElements.length).toBeGreaterThan(0);
    });

    it('shows elapsed time', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('1:30')).toBeInTheDocument();
    });

    it('shows progress percentage', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('50%')).toBeInTheDocument();
    });

    it('shows phase indicator', () => {
      render(<AttackFeed {...defaultProps} />);

      // Phase indicator shows the current phase
      const phaseElement = screen.getByText(/PHASE:/);
      expect(phaseElement).toBeInTheDocument();
      // Verify phase value is somewhere in the document
      expect(phaseElement.parentElement?.textContent).toMatch(/attack/i);
    });
  });

  describe('events display', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.events = [
        { type: 'gauntlet_start', data: { input_type: 'prompt' }, timestamp: Date.now(), seq: 1 },
        { type: 'gauntlet_phase', data: { phase: 'attack' }, timestamp: Date.now(), seq: 2 },
        {
          type: 'gauntlet_agent_active',
          data: { agent: 'claude', role: 'attacker' },
          timestamp: Date.now(),
          seq: 3,
        },
        {
          type: 'gauntlet_attack',
          data: { agent: 'claude', attack_type: 'injection' },
          timestamp: Date.now(),
          seq: 4,
        },
      ];
    });

    it('displays event count', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('4 events')).toBeInTheDocument();
    });

    it('displays gauntlet start event', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText(/Gauntlet started/)).toBeInTheDocument();
    });

    it('displays phase event', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText(/Phase:/)).toBeInTheDocument();
    });

    it('displays agent activation event', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText(/Agent.*activated/)).toBeInTheDocument();
    });

    it('displays attack event', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText(/launched attack/)).toBeInTheDocument();
    });
  });

  describe('finding events', () => {
    const onFindingClick = jest.fn();

    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.events = [
        {
          type: 'gauntlet_finding',
          data: {
            finding_id: 'f-1',
            severity: 'CRITICAL',
            category: 'injection',
            title: 'Prompt Injection',
            description: 'System prompt bypass',
            source: 'claude',
          },
          timestamp: Date.now(),
          seq: 1,
        },
      ];
      mockHookReturn.findings = [
        {
          finding_id: 'f-1',
          severity: 'CRITICAL',
          category: 'injection',
          title: 'Prompt Injection',
          description: 'System prompt bypass',
          source: 'claude',
        },
      ];
    });

    it('displays finding event with severity', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('CRITICAL')).toBeInTheDocument();
      expect(screen.getByText('Prompt Injection')).toBeInTheDocument();
    });

    it('calls onFindingClick when finding is clicked', async () => {
      const user = userEvent.setup();
      render(<AttackFeed {...defaultProps} onFindingClick={onFindingClick} />);

      await act(async () => {
        await user.click(screen.getByText('Prompt Injection'));
      });

      expect(onFindingClick).toHaveBeenCalledWith(
        expect.objectContaining({
          finding_id: 'f-1',
          severity: 'CRITICAL',
          title: 'Prompt Injection',
        }),
      );
    });
  });

  describe('agent stats', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.agents = new Map([
        ['claude', { name: 'claude', status: 'active', attackCount: 5, probeCount: 10 }],
        ['gpt-4', { name: 'gpt-4', status: 'complete', attackCount: 3, probeCount: 8 }],
      ]);
    });

    it('displays agent stats when showAgentStats is true', () => {
      render(<AttackFeed {...defaultProps} showAgentStats={true} />);

      expect(screen.getByText('claude')).toBeInTheDocument();
      expect(screen.getByText('gpt-4')).toBeInTheDocument();
    });

    it('hides agent stats when showAgentStats is false', () => {
      render(<AttackFeed {...defaultProps} showAgentStats={false} />);

      // Agent stats bar should not be visible
      expect(screen.queryByText('claude')).not.toBeInTheDocument();
    });

    it('shows aggregate stats', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('8 attacks')).toBeInTheDocument();
      expect(screen.getByText('18 probes')).toBeInTheDocument();
    });
  });

  describe('verdict display', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.verdict = {
        verdict: 'APPROVED',
        confidence: 0.95,
        riskScore: 0.1,
        robustnessScore: 0.9,
        findings: { critical: 0, high: 1, medium: 2, low: 3, total: 6 },
      };
    });

    it('displays verdict when present', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('APPROVED')).toBeInTheDocument();
    });

    it('displays confidence percentage', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('95% confidence')).toBeInTheDocument();
    });

    it('displays findings counts', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('1 HIGH')).toBeInTheDocument();
      expect(screen.getByText('2 MED')).toBeInTheDocument();
    });
  });

  describe('error state', () => {
    beforeEach(() => {
      mockHookReturn.status = 'error';
      mockHookReturn.error = 'WebSocket connection failed';
    });

    it('displays error message', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('WebSocket connection failed')).toBeInTheDocument();
    });

    it('shows reconnect button', () => {
      render(<AttackFeed {...defaultProps} />);

      expect(screen.getByText('RECONNECT')).toBeInTheDocument();
    });

    it('calls reconnect on button click', async () => {
      const user = userEvent.setup();
      render(<AttackFeed {...defaultProps} />);

      await act(async () => {
        await user.click(screen.getByText('RECONNECT'));
      });

      expect(mockReconnect).toHaveBeenCalled();
    });
  });

  describe('compact mode', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.events = [
        { type: 'gauntlet_progress', data: { progress: 0.5 }, timestamp: Date.now(), seq: 1 },
        { type: 'gauntlet_attack', data: { agent: 'claude' }, timestamp: Date.now(), seq: 2 },
      ];
    });

    it('filters progress events in compact mode', () => {
      render(<AttackFeed {...defaultProps} compact={true} />);

      // Progress event should be filtered out in compact mode
      expect(screen.queryByText(/Progress:/)).not.toBeInTheDocument();
      // Attack event should still show
      expect(screen.getByText(/launched attack/)).toBeInTheDocument();
    });
  });

  describe('event limit', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      // Create 50 events
      mockHookReturn.events = Array.from({ length: 50 }, (_, i) => ({
        type: 'gauntlet_attack',
        data: { agent: 'claude' },
        timestamp: Date.now() + i,
        seq: i,
      }));
    });

    it('limits displayed events based on maxEvents', () => {
      render(<AttackFeed {...defaultProps} maxEvents={10} />);

      expect(screen.getByText('10 events')).toBeInTheDocument();
    });
  });
});
