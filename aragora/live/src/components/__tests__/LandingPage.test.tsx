import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LandingPage } from '../LandingPage';

jest.mock('next/link', () => {
  const MockLink = ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  url: string;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  simulateMessage(data: object) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

function createJsonResponse(payload: unknown, ok = true) {
  return Promise.resolve({
    ok,
    status: ok ? 200 : 500,
    headers: { get: () => null },
    json: () => Promise.resolve(payload),
  });
}

function createHttpResponse(
  payload: unknown,
  options: { ok?: boolean; status?: number; retryAfter?: string | null } = {},
) {
  const { ok = true, status = ok ? 200 : 500, retryAfter = null } = options;
  return Promise.resolve({
    ok,
    status,
    headers: { get: (name: string) => (name.toLowerCase() === 'retry-after' ? retryAfter : null) },
    json: () => Promise.resolve(payload),
  });
}

function createReadyAssessResponse(question: string) {
  return createHttpResponse({
    type: 'ready',
    option: {
      id: 'original',
      label: 'Use original wording',
      description: question,
      originalQuestion: question,
      interpretedQuestion: question,
      debatePrompt: question,
      agents: 3,
      rounds: 2,
    },
  });
}

function createNuggetsAssessResponse(question: string) {
  return createHttpResponse({
    type: 'confirm',
    preflight: {
      title: 'This question could mean a few things',
      prompt: 'Pick the interpretation you want Aragora to debate.',
      options: [
        {
          id: 'interp-0',
          label: 'Practical food-safety first',
          description:
            'Focus on whether reheating pre-cooked chicken nuggets is safe and practical for a 4 year old.',
          originalQuestion: question,
          interpretedQuestion: 'Should I microwave pre-cooked chicken nuggets for my 4 year old?',
          debatePrompt: 'Should I microwave pre-cooked chicken nuggets for my 4 year old?',
          agents: 3,
          rounds: 2,
          recommended: true,
        },
        {
          id: 'interp-1',
          label: 'Philosophical chicken-status reading',
          description: 'Treat the question as a joke about whether the chickens are alive or dead.',
          originalQuestion: question,
          interpretedQuestion:
            'Is this really a joke about whether the chickens are alive or dead?',
          debatePrompt: 'Is this really a joke about whether the chickens are alive or dead?',
          agents: 3,
          rounds: 2,
        },
        {
          id: 'original',
          label: 'Use original wording',
          description: 'Debate the question exactly as written.',
          originalQuestion: question,
          interpretedQuestion: question,
          debatePrompt: question,
          agents: 3,
          rounds: 2,
        },
      ],
    },
  });
}

describe('LandingPage live debate preview', () => {
  const originalWebSocket = global.WebSocket;
  const mockFetch = global.fetch as jest.Mock;

  beforeAll(() => {
    (global as unknown as { WebSocket: typeof MockWebSocket }).WebSocket = MockWebSocket;
  });

  afterAll(() => {
    global.WebSocket = originalWebSocket;
  });

  beforeEach(() => {
    MockWebSocket.instances = [];
    mockFetch.mockReset();
  });

  it('shows a live public debate from recent spectate activity', async () => {
    const latestTimestamp = new Date().toISOString();
    const earlierTimestamp = new Date(Date.now() - 1000).toISOString();

    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/spectate/recent?count=40')) {
        return createJsonResponse({
          events: [
            {
              event_type: 'proposal',
              timestamp: latestTimestamp,
              data: {
                task: 'Should Aragora open the live debate feed on the homepage?',
                details:
                  'Expose the strongest public debate so visitors can evaluate agent disagreement before signing up.',
                agents: ['Strategist', 'Critic'],
              },
              debate_id: 'debate-live-1',
              pipeline_id: null,
              agent_name: 'Strategist',
              round_number: 1,
            },
            {
              event_type: 'round_start',
              timestamp: earlierTimestamp,
              data: {},
              debate_id: 'debate-live-1',
              pipeline_id: null,
              agent_name: null,
              round_number: 1,
            },
          ],
        });
      }

      if (url.endsWith('/api/v1/spectate/status')) {
        return createJsonResponse({
          active: true,
          recent_activity_window_seconds: 120,
          recent_event_count: 2,
          last_event_at: latestTimestamp,
        });
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<LandingPage apiBase="https://api.example.com" wsUrl="ws://spectate.example.com/ws" />);

    expect(await screen.findByText('LIVE DEBATE')).toBeInTheDocument();
    expect(screen.getByText('Watch agents argue in real time.')).toBeInTheDocument();
    expect(
      await screen.findByText('2 recent events discovered for this debate.'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Should Aragora open the live debate feed on the homepage?'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'Expose the strongest public debate so visitors can evaluate agent disagreement before signing up.',
      ),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    expect(MockWebSocket.instances[0].url).toBe('ws://spectate.example.com/spectate/debate-live-1');
    expect(screen.getByText('2 agents visible')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open spectator view' })).toHaveAttribute(
      'href',
      '/spectate/debate-live-1',
    );
  });

  it('streams new critique events into the public transcript in real time', async () => {
    const latestTimestamp = new Date().toISOString();

    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/v1/spectate/recent?count=40')) {
        return createJsonResponse({
          events: [
            {
              event_type: 'proposal',
              timestamp: latestTimestamp,
              data: {
                task: 'Should we expose live debates to new visitors?',
                details:
                  'Yes. A public feed proves the product is more than a static marketing promise.',
                agents: ['Planner', 'Skeptic'],
              },
              debate_id: 'debate-live-2',
              pipeline_id: null,
              agent_name: 'Planner',
              round_number: 1,
            },
          ],
        });
      }

      if (url.endsWith('/api/v1/spectate/status')) {
        return createJsonResponse({
          active: true,
          recent_activity_window_seconds: 120,
          recent_event_count: 1,
          last_event_at: latestTimestamp,
        });
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<LandingPage apiBase="https://api.example.com" wsUrl="ws://spectate.example.com/ws" />);

    await waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    const socket = MockWebSocket.instances[0];

    act(() => {
      socket.simulateOpen();
      socket.simulateMessage({
        type: 'metadata',
        task: 'Should we expose live debates to new visitors?',
        agents: ['Planner', 'Skeptic', 'Judge'],
      });
      socket.simulateMessage({
        type: 'critique',
        timestamp: 1774807805,
        agent: 'Skeptic',
        round: 1,
        details:
          'Counterpoint: do not fake liveness. Only stream it when the bridge has a real debate attached.',
      });
    });

    expect(await screen.findByText('STREAMING NOW')).toBeInTheDocument();
    expect(screen.getByText('3 agents visible')).toBeInTheDocument();
    expect(screen.getAllByText('Skeptic')).toHaveLength(2);
    expect(
      screen.getByText(
        'Counterpoint: do not fake liveness. Only stream it when the bridge has a real debate attached.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('CRITIQUE')).toBeInTheDocument();
  });
});

describe('LandingPage submission flow', () => {
  const mockFetch = global.fetch as jest.Mock;

  function installBaseFetchMock(
    postHandler: (body: Record<string, unknown>) => Promise<unknown>,
    options: {
      telemetryBodies?: Array<Record<string, unknown>>;
      feedbackBodies?: Array<Record<string, unknown>>;
      assessHandler?: (body: Record<string, unknown>) => Promise<unknown>;
    } = {},
  ) {
    const {
      telemetryBodies,
      feedbackBodies,
      assessHandler = async (body) => createReadyAssessResponse(String(body.question ?? '')),
    } = options;
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url.endsWith('/api/v1/spectate/recent?count=40')) {
        return createJsonResponse({ events: [] });
      }

      if (url.endsWith('/api/v1/spectate/status')) {
        return createJsonResponse({
          active: false,
          recent_activity_window_seconds: 120,
          recent_event_count: 0,
          last_event_at: null,
        });
      }

      if (url.endsWith('/api/v1/playground/assess')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        return assessHandler(body);
      }

      if (url.endsWith('/api/v1/playground/debate')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        return postHandler(body);
      }

      if (url.endsWith('/api/v1/playground/landing/events')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        telemetryBodies?.push(body);
        return createHttpResponse({ ok: true }, { status: 202 });
      }

      if (url.endsWith('/api/v1/playground/landing/feedback')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        feedbackBodies?.push(body);
        return createHttpResponse({ ok: true, report_id: 'lfb_test_1' }, { status: 202 });
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });
  }

  it('asks for confirmation before debating an ambiguous nuggets prompt', async () => {
    const postedBodies: Array<Record<string, unknown>> = [];
    const telemetryBodies: Array<Record<string, unknown>> = [];
    installBaseFetchMock(
      async (body) => {
        postedBodies.push(body);
        return createHttpResponse({
          id: 'debate-preview-1',
          topic: String(body.question),
          status: 'completed',
          rounds_used: 1,
          consensus_reached: false,
          confidence: 0,
          verdict: 'needs_review',
          duration_seconds: 4.2,
          participants: ['gpt', 'claude'],
          proposals: {
            gpt: 'Yes. Reheat the nuggets until hot all the way through.',
            claude: 'Microwaving pre-cooked nuggets is a normal practical choice.',
          },
          critiques: [],
          votes: [],
          dissenting_views: [],
          final_answer: 'Yes. Reheat the nuggets until hot all the way through.',
          result_mode: 'preview',
          result_warning: 'This landing result is a fast preview of parallel model outputs.',
          receipt: {
            receipt_id: 'LV-20260403-test01',
            question: String(body.question),
            verdict: 'needs_review',
            confidence: 0,
            consensus: {
              reached: false,
              method: 'landing_preview',
              confidence: 0,
              supporting_agents: ['gpt', 'claude'],
              dissenting_agents: [],
            },
            agents: ['gpt', 'claude'],
            rounds_used: 1,
            timestamp: '2026-04-03T12:00:00Z',
            signature: null,
            signature_algorithm: null,
          },
          receipt_hash: 'hash-preview-1',
        });
      },
      {
        telemetryBodies,
        assessHandler: async (body) => createNuggetsAssessResponse(String(body.question ?? '')),
      },
    );

    render(<LandingPage apiBase="https://api.example.com" wsUrl="ws://spectate.example.com/ws" />);

    fireEvent.change(screen.getByPlaceholderText('What decision are you facing?'), {
      target: {
        value:
          'I warmed up chicken nuggets in the microwave for my 4 year old, but what if the chickens are alive or dead?',
      },
    });
    fireEvent.submit(
      screen.getByRole('button', { name: 'Run a free debate' }).closest('form') as HTMLFormElement,
    );

    expect(await screen.findByText('This question could mean a few things')).toBeInTheDocument();
    expect(
      screen.getByText('Pick the interpretation you want Aragora to debate.'),
    ).toBeInTheDocument();
    expect(postedBodies).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: /Practical food-safety first/i }));

    await waitFor(() => {
      expect(postedBodies).toHaveLength(1);
    });

    expect(String(postedBodies[0].question)).toContain('pre-cooked chicken nuggets');
    expect(postedBodies[0].source).toBe('landing');
    expect(await screen.findByText('Quick Read')).toBeInTheDocument();
    expect(screen.getByText('You Asked')).toBeInTheDocument();
    expect(screen.getByText('Aragora Debated')).toBeInTheDocument();
    expect(telemetryBodies.some((entry) => entry.event_type === 'preflight_shown')).toBe(true);
    expect(telemetryBodies.some((entry) => entry.event_type === 'preflight_selected')).toBe(true);
    expect(telemetryBodies.some((entry) => entry.event_type === 'preview_rendered')).toBe(true);
  });

  it('shows actionable timeout copy for landing preview failures', async () => {
    const telemetryBodies: Array<Record<string, unknown>> = [];
    installBaseFetchMock(
      async () =>
        createHttpResponse(
          { code: 'landing_preview_timeout', timeout_seconds: 25 },
          { ok: false, status: 408 },
        ),
      { telemetryBodies },
    );

    render(<LandingPage apiBase="https://api.example.com" wsUrl="ws://spectate.example.com/ws" />);

    fireEvent.change(screen.getByPlaceholderText('What decision are you facing?'), {
      target: { value: 'Should we delay the migration by one quarter?' },
    });
    fireEvent.submit(
      screen.getByRole('button', { name: 'Run a free debate' }).closest('form') as HTMLFormElement,
    );

    expect(
      await screen.findByText(
        'The landing preview timed out after 25s. Shorten the prompt or pick one interpretation first.',
      ),
    ).toBeInTheDocument();
    expect(telemetryBodies.some((entry) => entry.event_type === 'preview_timeout')).toBe(true);
  });

  it('lets the user flag a wrong answer and return to the editor flow', async () => {
    const telemetryBodies: Array<Record<string, unknown>> = [];
    const feedbackBodies: Array<Record<string, unknown>> = [];
    installBaseFetchMock(
      async () =>
        createHttpResponse({
          id: 'debate-preview-2',
          topic: 'Should I microwave chicken nuggets for my kid?',
          status: 'completed',
          rounds_used: 1,
          consensus_reached: false,
          confidence: 0,
          verdict: 'needs_review',
          duration_seconds: 3.1,
          participants: ['gpt', 'claude'],
          proposals: {
            gpt: 'Yes. Reheat the nuggets until hot all the way through.',
            claude: 'Microwaving pre-cooked nuggets is practical for a child meal.',
          },
          critiques: [],
          votes: [],
          dissenting_views: [],
          final_answer: 'Yes. Reheat the nuggets until hot all the way through.',
          result_mode: 'preview',
          receipt: {
            receipt_id: 'LV-20260403-test02',
            question: 'Should I microwave chicken nuggets for my kid?',
            verdict: 'needs_review',
            confidence: 0,
            consensus: {
              reached: false,
              method: 'landing_preview',
              confidence: 0,
              supporting_agents: ['gpt', 'claude'],
              dissenting_agents: [],
            },
            agents: ['gpt', 'claude'],
            rounds_used: 1,
            timestamp: '2026-04-03T12:00:00Z',
            signature: null,
            signature_algorithm: null,
          },
          receipt_hash: 'hash-preview-2',
        }),
      {
        telemetryBodies,
        feedbackBodies,
        assessHandler: async (body) => createNuggetsAssessResponse(String(body.question ?? '')),
      },
    );

    render(<LandingPage apiBase="https://api.example.com" wsUrl="ws://spectate.example.com/ws" />);

    fireEvent.change(screen.getByPlaceholderText('What decision are you facing?'), {
      target: {
        value:
          'I warmed up chicken nuggets in the microwave for my 4 year old, but what if the chickens are alive or dead?',
      },
    });
    fireEvent.submit(
      screen.getByRole('button', { name: 'Run a free debate' }).closest('form') as HTMLFormElement,
    );
    fireEvent.click(await screen.findByRole('button', { name: /Practical food-safety first/i }));

    expect(await screen.findByText('Quick Read')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'This answer seems wrong' }));

    expect(
      await screen.findByText(
        'Edit the wording below and rerun the debate with one more specific detail.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText('Choose which version of the question to debate'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByDisplayValue(
        'I warmed up chicken nuggets in the microwave for my 4 year old, but what if the chickens are alive or dead?',
      ),
    ).toBeInTheDocument();
    expect(telemetryBodies.some((entry) => entry.event_type === 'wrong_answer_clicked')).toBe(true);
    expect(feedbackBodies).toHaveLength(1);
    expect(feedbackBodies[0]).toEqual(
      expect.objectContaining({
        question:
          'I warmed up chicken nuggets in the microwave for my 4 year old, but what if the chickens are alive or dead?',
        interpreted_question: 'Should I microwave pre-cooked chicken nuggets for my 4 year old?',
        final_answer: 'Yes. Reheat the nuggets until hot all the way through.',
        debate_id: 'debate-preview-2',
        result_mode: 'preview',
        result_warning:
          'Aragora debated the focused interpretation you chose before opening the full transcript.',
        verdict: 'needs_review',
        participant_count: 2,
        rewritten: true,
      }),
    );
  });

  it('cancels a pending focus frame when the page unmounts after a wrong answer', async () => {
    const telemetryBodies: Array<Record<string, unknown>> = [];
    const feedbackBodies: Array<Record<string, unknown>> = [];
    const originalRequestAnimationFrame = window.requestAnimationFrame;
    const originalCancelAnimationFrame = window.cancelAnimationFrame;
    const cancelAnimationFrame = jest.fn();

    Object.defineProperty(window, 'requestAnimationFrame', {
      configurable: true,
      value: jest.fn(() => 77),
    });
    Object.defineProperty(window, 'cancelAnimationFrame', {
      configurable: true,
      value: cancelAnimationFrame,
    });

    installBaseFetchMock(
      async () =>
        createHttpResponse({
          id: 'debate-preview-3',
          topic: 'Should I microwave chicken nuggets for my kid?',
          status: 'completed',
          rounds_used: 1,
          consensus_reached: false,
          confidence: 0,
          verdict: 'needs_review',
          duration_seconds: 2.2,
          participants: ['gpt', 'claude'],
          proposals: {
            gpt: 'Yes. Reheat the nuggets until hot all the way through.',
            claude: 'Microwaving pre-cooked nuggets is practical for a child meal.',
          },
          critiques: [],
          votes: [],
          dissenting_views: [],
          final_answer: 'Yes. Reheat the nuggets until hot all the way through.',
          result_mode: 'preview',
          receipt: {
            receipt_id: 'LV-20260403-test03',
            question: 'Should I microwave chicken nuggets for my kid?',
            verdict: 'needs_review',
            confidence: 0,
            consensus: {
              reached: false,
              method: 'landing_preview',
              confidence: 0,
              supporting_agents: ['gpt', 'claude'],
              dissenting_agents: [],
            },
            agents: ['gpt', 'claude'],
            rounds_used: 1,
            timestamp: '2026-04-03T12:00:00Z',
            signature: null,
            signature_algorithm: null,
          },
          receipt_hash: 'hash-preview-3',
        }),
      {
        telemetryBodies,
        feedbackBodies,
        assessHandler: async (body) => createNuggetsAssessResponse(String(body.question ?? '')),
      },
    );

    try {
      const view = render(
        <LandingPage apiBase="https://api.example.com" wsUrl="ws://spectate.example.com/ws" />,
      );

      fireEvent.change(screen.getByPlaceholderText('What decision are you facing?'), {
        target: {
          value:
            'I warmed up chicken nuggets in the microwave for my 4 year old, but what if the chickens are alive or dead?',
        },
      });
      fireEvent.submit(
        screen
          .getByRole('button', { name: 'Run a free debate' })
          .closest('form') as HTMLFormElement,
      );
      fireEvent.click(await screen.findByRole('button', { name: /Practical food-safety first/i }));
      expect(await screen.findByText('Quick Read')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'This answer seems wrong' }));

      expect(
        await screen.findByText(
          'Edit the wording below and rerun the debate with one more specific detail.',
        ),
      ).toBeInTheDocument();
      expect(window.requestAnimationFrame).toHaveBeenCalled();

      view.unmount();

      expect(cancelAnimationFrame).toHaveBeenCalledWith(77);
      expect(telemetryBodies.some((entry) => entry.event_type === 'wrong_answer_clicked')).toBe(
        true,
      );
      expect(feedbackBodies).toHaveLength(1);
    } finally {
      Object.defineProperty(window, 'requestAnimationFrame', {
        configurable: true,
        value: originalRequestAnimationFrame,
      });
      Object.defineProperty(window, 'cancelAnimationFrame', {
        configurable: true,
        value: originalCancelAnimationFrame,
      });
    }
  });
});
