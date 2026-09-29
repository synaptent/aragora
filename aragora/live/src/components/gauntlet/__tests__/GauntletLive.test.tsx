import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GauntletLive } from '../GauntletLive';

// Mock the hook
const mockReconnect = jest.fn();
const mockHookReturn = {
  status: 'connecting' as const,
  error: null as string | null,
  inputType: '',
  inputSummary: '',
  phase: 'init',
  progress: 0,
  agents: new Map(),
  findings: [] as Array<{
    finding_id: string;
    severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
    category: string;
    title: string;
    description: string;
    source: string;
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
  reconnectAttempt: 0,
  isConnected: false,
  events: [],
};

jest.mock('@/hooks/useGauntletWebSocket', () => ({ useGauntletWebSocket: () => mockHookReturn }));

describe('GauntletLive', () => {
  const defaultProps = {
    gauntletId: 'gauntlet-123',
    wsUrl: 'wss://test.com/ws',
    onComplete: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset mock values
    mockHookReturn.status = 'connecting';
    mockHookReturn.error = null;
    mockHookReturn.inputType = '';
    mockHookReturn.inputSummary = '';
    mockHookReturn.phase = 'init';
    mockHookReturn.progress = 0;
    mockHookReturn.agents = new Map();
    mockHookReturn.findings = [];
    mockHookReturn.verdict = null;
    mockHookReturn.elapsedSeconds = 0;
    mockHookReturn.reconnectAttempt = 0;
  });

  describe('initial render', () => {
    it('renders the gauntlet ID', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText(/ID: gauntlet-123/)).toBeInTheDocument();
    });

    it('shows connecting status initially', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('CONNECTING...')).toBeInTheDocument();
    });

    it('shows waiting for agents message', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('Waiting for agents...')).toBeInTheDocument();
    });
  });

  describe('streaming state', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.inputType = 'prompt';
      mockHookReturn.inputSummary = 'Test prompt for AI agent';
      mockHookReturn.phase = 'attack';
      mockHookReturn.progress = 0.5;
      mockHookReturn.elapsedSeconds = 120;
    });

    it('shows stress-test running status', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('STRESS-TEST RUNNING')).toBeInTheDocument();
    });

    it('displays input type', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText(/Input:/)).toBeInTheDocument();
      // Multiple elements may match "prompt" - use getAllByText
      const promptElements = screen.getAllByText(/prompt/i);
      expect(promptElements.length).toBeGreaterThan(0);
    });

    it('displays input summary', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('Test prompt for AI agent')).toBeInTheDocument();
    });

    it('displays elapsed time', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('2:00')).toBeInTheDocument();
    });

    it('displays progress bar', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('50%')).toBeInTheDocument();
      expect(screen.getByText(/attack/i)).toBeInTheDocument();
    });
  });

  describe('agents panel', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.agents = new Map([
        [
          'claude',
          { name: 'claude', role: 'attacker', status: 'active', attackCount: 5, probeCount: 10 },
        ],
        [
          'gpt-4',
          { name: 'gpt-4', role: 'analyst', status: 'idle', attackCount: 3, probeCount: 8 },
        ],
      ]);
    });

    it('displays agent count', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText(/AGENTS \(2\)/)).toBeInTheDocument();
    });

    it('displays agent names', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('claude')).toBeInTheDocument();
      expect(screen.getByText('gpt-4')).toBeInTheDocument();
    });

    it('displays agent attack and probe counts', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('5 attacks')).toBeInTheDocument();
      expect(screen.getByText('10 probes')).toBeInTheDocument();
    });

    it('can collapse agents panel', async () => {
      const user = userEvent.setup();
      render(<GauntletLive {...defaultProps} />);

      await act(async () => {
        await user.click(screen.getAllByText('[COLLAPSE]')[0]);
      });

      expect(screen.getByText('[EXPAND]')).toBeInTheDocument();
    });
  });

  describe('findings panel', () => {
    beforeEach(() => {
      mockHookReturn.status = 'streaming';
      mockHookReturn.findings = [
        {
          finding_id: 'f-1',
          severity: 'CRITICAL',
          category: 'injection',
          title: 'Prompt Injection Vulnerability',
          description: 'System prompt can be overridden',
          source: 'claude',
        },
        {
          finding_id: 'f-2',
          severity: 'HIGH',
          category: 'data-leak',
          title: 'Information Disclosure',
          description: 'Sensitive data exposed',
          source: 'gpt-4',
        },
      ];
    });

    it('displays findings count', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText(/FINDINGS \(2\)/)).toBeInTheDocument();
    });

    it('displays finding titles', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('Prompt Injection Vulnerability')).toBeInTheDocument();
      expect(screen.getByText('Information Disclosure')).toBeInTheDocument();
    });

    it('displays severity badges', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('CRITICAL')).toBeInTheDocument();
      expect(screen.getByText('HIGH')).toBeInTheDocument();
    });

    it('shows live findings summary badges', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('1 CRITICAL')).toBeInTheDocument();
      expect(screen.getByText('1 HIGH')).toBeInTheDocument();
    });
  });

  describe('verdict display', () => {
    beforeEach(() => {
      mockHookReturn.status = 'complete';
      mockHookReturn.verdict = {
        verdict: 'APPROVED_WITH_CONDITIONS',
        confidence: 0.85,
        riskScore: 0.3,
        robustnessScore: 0.75,
        findings: { critical: 0, high: 2, medium: 3, low: 5, total: 10 },
      };
    });

    it('displays verdict', () => {
      render(<GauntletLive {...defaultProps} />);

      // Verdict text replaces underscores with spaces
      expect(screen.getByText(/APPROVED.+CONDITIONS/i)).toBeInTheDocument();
    });

    it('displays confidence', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('Confidence: 85%')).toBeInTheDocument();
    });

    it('displays risk score', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('30')).toBeInTheDocument(); // Risk score
    });

    it('displays robustness score', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('75')).toBeInTheDocument(); // Robustness score
    });

    it('displays findings summary', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('2 High')).toBeInTheDocument();
      expect(screen.getByText('3 Medium')).toBeInTheDocument();
      expect(screen.getByText('5 Low')).toBeInTheDocument();
      expect(screen.getByText('10 Total')).toBeInTheDocument();
    });

    it('calls onComplete when verdict is received', () => {
      const onComplete = jest.fn();
      render(<GauntletLive {...defaultProps} onComplete={onComplete} />);

      expect(onComplete).toHaveBeenCalledWith(mockHookReturn.verdict);
    });
  });

  describe('error state', () => {
    beforeEach(() => {
      mockHookReturn.status = 'error';
      mockHookReturn.error = 'Connection lost';
    });

    it('displays error message', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('Error: Connection lost')).toBeInTheDocument();
    });

    it('shows reconnect button', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText('[RECONNECT]')).toBeInTheDocument();
    });

    it('calls reconnect when button clicked', async () => {
      const user = userEvent.setup();
      render(<GauntletLive {...defaultProps} />);

      await act(async () => {
        await user.click(screen.getByText('[RECONNECT]'));
      });

      expect(mockReconnect).toHaveBeenCalled();
    });
  });

  describe('reconnecting state', () => {
    beforeEach(() => {
      mockHookReturn.status = 'connecting';
      mockHookReturn.reconnectAttempt = 3;
    });

    it('shows reconnection indicator', () => {
      render(<GauntletLive {...defaultProps} />);

      expect(screen.getByText(/RECONNECTING \(3\/15\)/)).toBeInTheDocument();
    });
  });
});
