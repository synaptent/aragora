import { render, screen } from '@testing-library/react';
import { LiveDemoSection } from '../LiveDemoSection';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

jest.mock('@/context/ThemeContext', () => ({
  useTheme: () => ({ theme: 'dark', setTheme: jest.fn() }),
}));

const mockUseSpectate = jest.fn();

jest.mock('@/hooks/useSpectate', () => ({
  useSpectate: (...args: unknown[]) => mockUseSpectate(...args),
}));

describe('LiveDemoSection', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading bridge copy before spectate status arrives', () => {
    mockUseSpectate.mockReturnValue({
      status: null,
      loaded: false,
      connected: false,
      events: [],
      refresh: jest.fn(),
    });

    render(<LiveDemoSection />);

    expect(screen.getByTestId('live-demo-section')).toBeInTheDocument();
    expect(screen.getByText('Checking public bridge')).toBeInTheDocument();
    expect(
      screen.getByText('Checking public live bridge before showing recent activity.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Looping public debate')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Should a fast-growing software org split the monolith now or sequence the migration later?',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open full spectate view' })).toHaveAttribute(
      'href',
      '/spectate',
    );
  });

  it('shows a live transcript when recent debate events are available', () => {
    mockUseSpectate.mockReturnValue({
      status: {
        active: true,
        subscribers: 3,
        buffer_size: 12,
        bridge_state: 'activity_unattributed',
        last_event_at: '2026-03-28T20:00:00Z',
        activity_age_seconds: 34,
        recent_activity_window_seconds: 120,
        recent_event_count: 9,
        live_debate_count: 0,
        live_debate_ids: [],
        live_debates: [],
        unattributed_recent_event_count: 9,
      },
      loaded: true,
      connected: true,
      events: [
        {
          event_type: 'proposal',
          timestamp: '2026-03-28T20:00:01Z',
          data: {
            task: 'Should we split checkout into its own service?',
            details:
              'Checkout should move first because it changes weekly and already has a clear API edge.',
          },
          debate_id: 'debate-1',
          pipeline_id: null,
          agent_name: 'Strategic Analyst',
          round_number: 1,
        },
        {
          event_type: 'critique',
          timestamp: '2026-03-28T20:00:05Z',
          data: {
            details:
              'That still leaves deployment risk centralized unless the owning team can ship independently.',
            metric: 0.74,
          },
          debate_id: 'debate-1',
          pipeline_id: null,
          agent_name: "Devil's Advocate",
          round_number: 1,
        },
        {
          event_type: 'consensus',
          timestamp: '2026-03-28T20:00:09Z',
          data: {
            details:
              'Consensus reached: split checkout first, then reassess after two release cycles.',
            metric: 0.81,
          },
          debate_id: 'debate-1',
          pipeline_id: null,
          agent_name: 'Systems Judge',
          round_number: 2,
        },
      ],
      refresh: jest.fn(),
    });

    render(<LiveDemoSection />);

    expect(screen.getByText('Bridge active')).toBeInTheDocument();
    expect(screen.getByText('9 recent events in the last 2 minutes.')).toBeInTheDocument();
    expect(screen.getByText('Last activity 34s ago')).toBeInTheDocument();
    expect(screen.getByText('Live public debate')).toBeInTheDocument();
    expect(screen.getByText('Should we split checkout into its own service?')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Checkout should move first because it changes weekly and already has a clear API edge.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'That still leaves deployment risk centralized unless the owning team can ship independently.',
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('live-debate-event')).toHaveLength(3);
    expect(screen.getByRole('link', { name: 'Watch this debate live' })).toHaveAttribute(
      'href',
      '/spectate/debate-1',
    );
  });
});
