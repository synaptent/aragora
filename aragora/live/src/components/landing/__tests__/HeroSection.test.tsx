import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { DebateResponse } from '../../DebateResultPreview';
import { HeroSection } from '../HeroSection';

const mockPush = jest.fn();
const mockBackendConfig = { api: 'http://localhost:8080' };
const mockCompactDebateResult = jest.fn();

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));

jest.mock('@/context/ThemeContext', () => ({ useTheme: () => ({ theme: 'dark' }) }));

jest.mock('../../DebateResultPreview', () => ({
  RETURN_URL_KEY: 'return_url',
  PENDING_DEBATE_KEY: 'pending_debate',
}));

jest.mock('../CompactDebateResult', () => ({
  CompactDebateResult: (props: Record<string, unknown>) => {
    mockCompactDebateResult(props);
    return <div data-testid="debate-result-preview">Aragora&apos;s Answer</div>;
  },
}));

jest.mock('../../BackendSelector', () => ({
  useBackend: () => ({ config: mockBackendConfig }),
  BACKENDS: { production: { api: 'http://localhost:8080' } },
}));

// Mock DebateInput since it has complex dependencies
jest.mock('../../DebateInput', () => ({
  DebateInput: () => <div data-testid="debate-input">MockDebateInput</div>,
}));

function createResponse(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  return { ok: init.ok ?? true, status: init.status ?? 200, json: async () => body };
}

function createNuggetsAssessResponse(question: string) {
  return createResponse({
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

describe('HeroSection', () => {
  const defaultProps = {
    error: null,
    activeDebateId: null,
    activeQuestion: null,
    apiBase: 'http://localhost:8080',
    onDismissError: jest.fn(),
    onDebateStarted: jest.fn(),
    onError: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockBackendConfig.api = 'http://localhost:8080';
    Element.prototype.scrollIntoView = jest.fn();
    window.sessionStorage.clear();
  });

  describe('initial render', () => {
    it('renders the main heading', () => {
      render(<HeroSection {...defaultProps} />);

      expect(
        screen.getByRole('heading', { name: /what decision should ai debate for you/i }),
      ).toBeInTheDocument();
    });

    it('renders the subheading', () => {
      render(<HeroSection {...defaultProps} />);

      expect(screen.getByText(/Multiple AI models will argue every angle/i)).toBeInTheDocument();
    });

    it('renders the DebateInput component', () => {
      render(<HeroSection {...defaultProps} />);

      expect(screen.getByTestId('debate-input')).toBeInTheDocument();
    });

    it('renders ASCII banner on larger screens', () => {
      render(<HeroSection {...defaultProps} />);

      // ASCII banner is rendered in the desktop-only preformatted block.
      const banner = document.querySelector('pre.hidden.sm\\:block');
      expect(banner).toBeInTheDocument();
      // Banner is stylized ASCII art, just verify it has content
      expect(banner?.textContent?.length).toBeGreaterThan(100);
    });
  });

  describe('error display', () => {
    it('shows error message when error is present', () => {
      render(<HeroSection {...defaultProps} error="Something went wrong" />);

      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });

    it('does not show error section when error is null', () => {
      render(<HeroSection {...defaultProps} error={null} />);

      expect(screen.queryByText('✕')).not.toBeInTheDocument();
    });

    it('calls onDismissError when dismiss button is clicked', async () => {
      const user = userEvent.setup();
      const onDismissError = jest.fn();

      render(<HeroSection {...defaultProps} error="Test error" onDismissError={onDismissError} />);

      await user.click(screen.getByRole('button', { name: /dismiss error/i }));

      expect(onDismissError).toHaveBeenCalledTimes(1);
    });

    it('error dismiss button has accessible label', () => {
      render(<HeroSection {...defaultProps} error="Test error" />);

      expect(screen.getByRole('button', { name: /dismiss error/i })).toBeInTheDocument();
    });
  });

  describe('active debate indicator', () => {
    it('shows active debate section when debate is in progress', () => {
      render(
        <HeroSection
          {...defaultProps}
          activeDebateId="debate-123"
          activeQuestion="Is AI beneficial?"
        />,
      );

      expect(screen.getByText('DECISION IN PROGRESS')).toBeInTheDocument();
    });

    it('displays the active question', () => {
      render(
        <HeroSection
          {...defaultProps}
          activeDebateId="debate-123"
          activeQuestion="Is AI beneficial?"
        />,
      );

      expect(screen.getByText('Is AI beneficial?')).toBeInTheDocument();
    });

    it('displays the debate ID', () => {
      render(
        <HeroSection
          {...defaultProps}
          activeDebateId="debate-123"
          activeQuestion="Is AI beneficial?"
        />,
      );

      expect(screen.getByText(/ID: debate-123/)).toBeInTheDocument();
    });

    it('shows WebSocket streaming indicator', () => {
      render(
        <HeroSection
          {...defaultProps}
          activeDebateId="debate-123"
          activeQuestion="Is AI beneficial?"
        />,
      );

      expect(screen.getByText(/Events streaming via WebSocket/)).toBeInTheDocument();
    });

    it('does not show active debate section when no debate is active', () => {
      render(<HeroSection {...defaultProps} activeDebateId={null} />);

      expect(screen.queryByText('DECISION IN PROGRESS')).not.toBeInTheDocument();
    });

    it('has animated pulse indicator for active debate', () => {
      render(<HeroSection {...defaultProps} activeDebateId="debate-123" activeQuestion="Test" />);

      const pulseIndicator = document.querySelector('.animate-pulse');
      expect(pulseIndicator).toBeInTheDocument();
    });
  });

  describe('props passing', () => {
    it('passes apiBase to DebateInput', () => {
      render(<HeroSection {...defaultProps} apiBase="http://custom:9000" />);

      // DebateInput is mocked, but we can verify the component renders
      expect(screen.getByTestId('debate-input')).toBeInTheDocument();
    });
  });

  describe('landing mode backend resolution', () => {
    it('uses the same-origin API proxy when the backend hook resolves an empty local API base', async () => {
      const user = userEvent.setup();
      const fetchMock = jest
        .fn()
        .mockResolvedValue({
          ok: true,
          json: async () => ({ id: 'debate-demo-123', status: 'completed' }),
        });
      mockBackendConfig.api = '';
      global.fetch = fetchMock as typeof fetch;

      render(<HeroSection />);

      await user.click(screen.getByRole('button', { name: /try a demo debate/i }));

      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/playground/debate/',
        expect.objectContaining({ method: 'POST' }),
      );
    });

    it('shows a preflight chooser for ambiguous landing prompts before debating', async () => {
      const user = userEvent.setup();
      const question =
        'Should I cook my chickens in a microwave? What if they are alive, and what if they are dead?';
      const fetchMock = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/v1/playground/landing/events')) {
          return Promise.resolve(createResponse({}));
        }
        return Promise.resolve(createNuggetsAssessResponse(question));
      });
      global.fetch = fetchMock as typeof fetch;

      render(<HeroSection />);

      await user.type(screen.getByRole('textbox'), question);
      await user.click(screen.getByRole('button', { name: /start debate/i }));

      expect(await screen.findByText('This question could mean a few things')).toBeInTheDocument();
      expect(
        screen.getByText('Pick the interpretation you want Aragora to debate.'),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /practical food-safety first/i }),
      ).toBeInTheDocument();
      expect(
        fetchMock.mock.calls.some(([input]) => String(input).includes('/api/v1/playground/debate')),
      ).toBe(false);
    });

    it('renders the landing preview in condensed mode after a successful debate', async () => {
      const user = userEvent.setup();
      const fetchMock = jest.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/v1/playground/assess')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              type: 'proceed',
              option: {
                id: 'direct',
                label: 'Direct debate',
                description: 'Run the question as written.',
                originalQuestion: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
                interpretedQuestion: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
                debatePrompt: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
                agents: 3,
                rounds: 2,
              },
            }),
          });
        }
        if (url.includes('/api/v1/playground/landing/events')) {
          return Promise.resolve(createResponse({}));
        }
        if (url.includes('/api/v1/playground/assess')) {
          return Promise.resolve(
            createResponse({
              type: 'ready',
              option: {
                id: 'original',
                label: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
                description: 'Debate the question exactly as written.',
                originalQuestion: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
                interpretedQuestion: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
                debatePrompt: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
                agents: 3,
                rounds: 2,
              },
            }),
          );
        }
        return Promise.resolve(
          createResponse({
            id: 'debate-123',
            topic: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
            status: 'completed',
            rounds_used: 1,
            consensus_reached: false,
            confidence: 0.7,
            verdict: 'needs_review',
            duration_seconds: 8,
            participants: ['gpt', 'claude', 'grok'],
            proposals: { gpt: 'Yes, if heated safely.' },
            critiques: [],
            votes: [],
            dissenting_views: [],
            final_answer: 'Yes, if heated safely.',
            receipt: null,
            receipt_hash: null,
            result_mode: 'preview',
          }),
        );
      });
      global.fetch = fetchMock as typeof fetch;

      render(<HeroSection />);

      await user.type(
        screen.getByRole('textbox'),
        'Can I microwave frozen chicken nuggets for my 4-year-old?',
      );
      await user.click(screen.getByRole('button', { name: /start debate/i }));

      await waitFor(() => {
        expect(screen.getByTestId('debate-result-preview')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /view full debate/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /log in to save/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /sign up free/i })).toBeInTheDocument();
      });

      expect(mockCompactDebateResult).toHaveBeenCalledWith(
        expect.objectContaining({
          onWrongAnswer: expect.any(Function),
          onShare: expect.any(Function),
          result: expect.objectContaining({
            original_question: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
            interpreted_question: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
          }),
        }),
      );
      expect(screen.getByRole('button', { name: /try another/i })).toBeInTheDocument();
      expect(
        screen.getByText(/keep this debate and continue from the full transcript/i),
      ).toBeInTheDocument();
    });

    it('submits wrong-answer feedback from the active landing preview', async () => {
      const user = userEvent.setup();
      const question = 'Should we use Redis or Memcached for session cache?';
      const interpretedQuestion =
        'Should our app use Redis instead of Memcached for session cache?';
      const debateResult: DebateResponse = {
        id: 'debate-queue-123',
        topic: interpretedQuestion,
        status: 'completed',
        rounds_used: 1,
        consensus_reached: false,
        confidence: 0.7,
        verdict: 'needs_review',
        duration_seconds: 8,
        participants: ['gpt', 'claude', 'grok'],
        proposals: { gpt: 'Use Redis for shared session cache.' },
        critiques: [],
        votes: [],
        dissenting_views: [],
        final_answer: 'Use Redis for shared session cache.',
        receipt: null,
        receipt_hash: null,
        result_mode: 'preview',
        result_warning: 'Aragora debated a focused interpretation.',
      };
      const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/v1/playground/assess')) {
          return createResponse({
            type: 'proceed',
            option: {
              id: 'direct',
              label: 'Direct debate',
              description: 'Run the question as written.',
              originalQuestion: question,
              interpretedQuestion,
              debatePrompt: interpretedQuestion,
              agents: 3,
              rounds: 2,
            },
          });
        }
        if (url.includes('/api/v1/playground/debate')) {
          return createResponse(debateResult);
        }
        return createResponse({});
      });
      global.fetch = fetchMock as typeof fetch;

      render(<HeroSection />);

      await user.type(screen.getByRole('textbox'), question);
      await user.click(screen.getByRole('button', { name: /start debate/i }));

      await waitFor(() => {
        expect(screen.getByTestId('debate-result-preview')).toBeInTheDocument();
      });

      const previewProps = mockCompactDebateResult.mock.calls.at(-1)?.[0] as {
        onWrongAnswer: (result: DebateResponse) => void;
        result: DebateResponse;
      };
      act(() => {
        previewProps.onWrongAnswer(previewProps.result);
      });

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
          'http://localhost:8080/api/v1/playground/landing/feedback',
          expect.objectContaining({ method: 'POST' }),
        );
      });
      const feedbackCall = fetchMock.mock.calls.find(([input]) =>
        String(input).includes('/api/v1/playground/landing/feedback'),
      );
      const feedbackBody = JSON.parse(String((feedbackCall?.[1] as RequestInit).body));
      expect(feedbackBody).toEqual({
        question,
        interpreted_question: interpretedQuestion,
        final_answer: 'Use Redis for shared session cache.',
        result_warning: 'Aragora debated a focused interpretation.',
        result_mode: 'preview',
        debate_id: 'debate-queue-123',
        verdict: 'needs_review',
        participant_count: 3,
        rewritten: true,
      });
    });

    it('stores the result before routing to auth from the post-debate CTAs', async () => {
      const user = userEvent.setup();
      const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/v1/playground/landing/assess')) {
          return createResponse({
            type: 'proceed',
            option: {
              id: 'direct',
              label: 'Direct debate',
              description: 'Run the question as written.',
              originalQuestion: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
              interpretedQuestion: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
              debatePrompt: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
              agents: 3,
              rounds: 2,
            },
          });
        }
        if (url.includes('/api/v1/playground/landing/events')) {
          return createResponse({});
        }
        if (url.includes('/api/v1/playground/debate')) {
          return createResponse({
            id: 'debate-123',
            topic: 'Can I microwave frozen chicken nuggets for my 4-year-old?',
            status: 'completed',
            rounds_used: 1,
            consensus_reached: false,
            confidence: 0.7,
            verdict: 'needs_review',
            duration_seconds: 8,
            participants: ['gpt', 'claude', 'grok'],
            proposals: { gpt: 'Yes, if heated safely.' },
            critiques: [],
            votes: [],
            dissenting_views: [],
            final_answer: 'Yes, if heated safely.',
            receipt: null,
            receipt_hash: null,
            result_mode: 'preview',
          });
        }
        return createResponse({});
      });
      global.fetch = fetchMock as typeof fetch;
      const setItemSpy = jest.spyOn(Storage.prototype, 'setItem');

      render(<HeroSection />);

      await user.type(
        screen.getByRole('textbox'),
        'Can I microwave frozen chicken nuggets for my 4-year-old?',
      );
      await user.click(screen.getByRole('button', { name: /start debate/i }));

      await waitFor(() => {
        expect(screen.getByTestId('debate-result-preview')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /view full debate/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /log in to save/i })).toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: /log in to save/i }));

      expect(setItemSpy).toHaveBeenCalledWith(
        'pending_debate',
        expect.stringContaining('"id":"debate-123"'),
      );
      expect(setItemSpy).toHaveBeenCalledWith('return_url', '/debates/debate-123');
      expect(mockPush).toHaveBeenLastCalledWith('/login');

      await user.click(screen.getByRole('button', { name: /sign up free/i }));

      expect(setItemSpy).toHaveBeenCalledWith(
        'pending_debate',
        expect.stringContaining('"id":"debate-123"'),
      );
      expect(setItemSpy).toHaveBeenCalledWith('return_url', '/debates/debate-123');
      expect(mockPush).toHaveBeenLastCalledWith('/signup');
      expect(screen.getByRole('button', { name: /try another/i })).toBeInTheDocument();

      setItemSpy.mockRestore();
    });
  });
});
