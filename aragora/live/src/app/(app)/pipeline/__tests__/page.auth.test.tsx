import { render, waitFor } from '@testing-library/react';
import { useSearchParams } from 'next/navigation';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import PipelinePage from '../page';

jest.mock('next/dynamic', () => () => () => null);
jest.mock('@/hooks/usePipeline', () => ({
  usePipeline: () => ({
    pipelineData: null,
    setPipelineData: jest.fn(),
    isDemo: false,
    createFromIdeas: jest.fn(),
    createFromBrainDump: jest.fn(),
    createFromDebate: jest.fn(),
    advanceStage: jest.fn(),
    executePipeline: jest.fn(),
    executeWithSelfImprove: jest.fn(),
    approveTransition: jest.fn(),
    rejectTransition: jest.fn(),
    loadDemo: jest.fn(),
    reset: jest.fn(),
    loading: false,
    executing: false,
    error: null,
  }),
}));
jest.mock('@/hooks/usePipelineWebSocket', () => ({
  usePipelineWebSocket: () => ({ isConnected: false, completedStages: [], streamedNodes: [] }),
}));
jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: () => ({ data: undefined, isLoading: false }),
}));
jest.mock('@/components/pipeline/GoldenPathSummary', () => ({ GoldenPathSummary: () => null }));
jest.mock('@/components/pipeline-canvas/StatusBadge', () => ({ StatusBadge: () => null }));
jest.mock('@/components/pipeline-canvas/ExecutionProgressOverlay', () => ({ ExecutionProgressOverlay: () => null }));
jest.mock('@/components/pipeline-canvas/FeedbackLoopPanel', () => ({ FeedbackLoopPanel: () => null }));
jest.mock('@/components/pipeline-canvas/AutoTransitionSuggestion', () => ({ AutoTransitionSuggestion: () => null }));
jest.mock('@/components/wizards/UseCaseWizard', () => ({ UseCaseWizard: () => null }));

const mockFetch = global.fetch as jest.Mock;

describe('PipelinePage authenticated requests', () => {
  beforeEach(() => {
    storeTestSession();
    (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams('from=debate&id=debate-a'));
    mockFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
  });

  afterEach(() => {
    clearTestSession();
    (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams());
  });

  it('sends the session token when importing a debate from ?from=debate', async () => {
    render(<PipelinePage />);

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(authHeaderOf(mockFetch, '/api/v1/debates/debate-a')).toBe(`Bearer ${TEST_SESSION_TOKEN}`);
  });
});
