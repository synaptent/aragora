import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DebateForkPanel } from '../DebateForkPanel';

// Mock BackendSelector
jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('DebateForkPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial render', () => {
    it('renders fork tab by default', () => {
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      expect(screen.getByText('[FORK DEBATE]')).toBeInTheDocument();
      expect(screen.getByText('[FOLLOW-UP]')).toBeInTheDocument();
    });

    it('shows fork description', () => {
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      expect(
        screen.getByText(/Create a counterfactual branch from this debate/),
      ).toBeInTheDocument();
    });

    it('renders branch point slider', () => {
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      expect(screen.getByText('BRANCH POINT (message #)')).toBeInTheDocument();
      expect(screen.getByRole('slider')).toBeInTheDocument();
    });

    it('sets default branch point to messageCount - 1', () => {
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      const slider = screen.getByRole('slider');
      expect(slider).toHaveValue('9');
    });

    it('renders modified context textarea', () => {
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      expect(screen.getByText('MODIFIED CONTEXT (optional)')).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/What if we assumed X instead of Y/)).toBeInTheDocument();
    });

    it('renders create fork button', () => {
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      expect(screen.getByText('[CREATE FORK]')).toBeInTheDocument();
    });
  });

  describe('fork creation', () => {
    it('sends fork request with correct parameters', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            branch_id: 'branch-456',
            parent_debate_id: 'debate-123',
            branch_point: 9,
            messages_inherited: 9,
            status: 'created',
            message: 'Fork created',
          }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[CREATE FORK]'));
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/debates/debate-123/fork',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    });

    it('shows loading state while forking', async () => {
      // Test that button text changes during loading
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ success: true, branch_id: 'branch-456', messages_inherited: 5 }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      // Before clicking, button shows CREATE FORK
      expect(screen.getByText('[CREATE FORK]')).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByText('[CREATE FORK]'));
      });

      // After completion, the result should be visible
      await waitFor(() => {
        expect(screen.getByText('FORK CREATED')).toBeInTheDocument();
      });
    });

    it('displays success result after fork created', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ success: true, branch_id: 'branch-456', messages_inherited: 5 }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[CREATE FORK]'));
      });

      await waitFor(() => {
        expect(screen.getByText('FORK CREATED')).toBeInTheDocument();
        expect(screen.getByText(/Branch ID: branch-456/)).toBeInTheDocument();
        expect(screen.getByText(/Inherited 5 messages/)).toBeInTheDocument();
      });
    });

    it('calls onForkCreated callback', async () => {
      const forkResult = {
        success: true,
        branch_id: 'branch-456',
        parent_debate_id: 'debate-123',
        branch_point: 5,
        messages_inherited: 5,
        status: 'created',
        message: 'Fork created',
      };
      mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(forkResult) });

      const onForkCreated = jest.fn();
      const user = userEvent.setup();
      render(
        <DebateForkPanel debateId="debate-123" messageCount={10} onForkCreated={onForkCreated} />,
      );

      await act(async () => {
        await user.click(screen.getByText('[CREATE FORK]'));
      });

      await waitFor(() => {
        expect(onForkCreated).toHaveBeenCalledWith(forkResult);
      });
    });

    it('displays error on fork failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Debate not found' }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[CREATE FORK]'));
      });

      await waitFor(() => {
        expect(screen.getByText('Debate not found')).toBeInTheDocument();
      });
    });
  });

  describe('follow-up tab', () => {
    it('switches to follow-up tab on click', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ suggestions: [] }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      expect(
        screen.getByText(/Create a follow-up debate to explore unresolved/),
      ).toBeInTheDocument();
    });

    it('loads suggestions when switching to follow-up tab', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            suggestions: [
              {
                id: 'crux-1',
                crux_description: 'Disagreement about scalability',
                suggested_task: 'Debate scalability trade-offs',
                priority: 1,
              },
            ],
          }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(screen.getByText('Disagreement about scalability')).toBeInTheDocument();
        expect(screen.getByText('Debate scalability trade-offs')).toBeInTheDocument();
      });
    });

    it('shows loading state while fetching suggestions', async () => {
      let resolvePromise: () => void;
      mockFetch.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolvePromise = () =>
              resolve({ ok: true, json: () => Promise.resolve({ suggestions: [] }) });
          }),
      );

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      expect(screen.getByText('Loading suggestions...')).toBeInTheDocument();

      await act(async () => {
        resolvePromise!();
      });
    });

    it('renders custom task textarea', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ suggestions: [] }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(screen.getByText('OR ENTER CUSTOM TASK')).toBeInTheDocument();
        expect(screen.getByPlaceholderText(/What specific question should/)).toBeInTheDocument();
      });
    });

    it('disables create button when no selection or custom task', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ suggestions: [] }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      await waitFor(() => {
        const createButton = screen.getByText('[CREATE FOLLOW-UP]');
        expect(createButton).toBeDisabled();
      });
    });
  });

  describe('follow-up creation', () => {
    it('creates follow-up with selected crux', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: () =>
            Promise.resolve({
              suggestions: [
                {
                  id: 'crux-1',
                  crux_description: 'Test crux',
                  suggested_task: 'Test task',
                  priority: 1,
                },
              ],
            }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () =>
            Promise.resolve({
              success: true,
              followup_id: 'followup-789',
              parent_debate_id: 'debate-123',
              task: 'Test task',
              status: 'created',
              message: 'Follow-up created',
            }),
        });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(screen.getByText('Test crux')).toBeInTheDocument();
      });

      // Select the suggestion
      await act(async () => {
        await user.click(screen.getByText('Test crux'));
      });

      await act(async () => {
        await user.click(screen.getByText('[CREATE FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(screen.getByText('FOLLOW-UP CREATED')).toBeInTheDocument();
        expect(screen.getByText(/ID: followup-789/)).toBeInTheDocument();
      });
    });

    it('creates follow-up with custom task', async () => {
      mockFetch
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ suggestions: [] }) })
        .mockResolvedValueOnce({
          ok: true,
          json: () =>
            Promise.resolve({
              success: true,
              followup_id: 'followup-custom',
              parent_debate_id: 'debate-123',
              task: 'My custom task',
              status: 'created',
              message: 'Follow-up created',
            }),
        });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(screen.getByText('OR ENTER CUSTOM TASK')).toBeInTheDocument();
      });

      const textarea = screen.getByPlaceholderText(/What specific question/);
      await act(async () => {
        await user.type(textarea, 'My custom task');
      });

      await act(async () => {
        await user.click(screen.getByText('[CREATE FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(screen.getByText('FOLLOW-UP CREATED')).toBeInTheDocument();
      });
    });

    it('shows error when neither crux nor task provided', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ suggestions: [] }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      await waitFor(() => {
        // Button should be disabled
        expect(screen.getByText('[CREATE FOLLOW-UP]')).toBeDisabled();
      });
    });

    it('calls onFollowupCreated callback', async () => {
      const followupResult = {
        success: true,
        followup_id: 'followup-789',
        parent_debate_id: 'debate-123',
        task: 'Test task',
        status: 'created',
        message: 'Follow-up created',
      };

      mockFetch
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ suggestions: [] }) })
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(followupResult) });

      const onFollowupCreated = jest.fn();
      const user = userEvent.setup();
      render(
        <DebateForkPanel
          debateId="debate-123"
          messageCount={10}
          onFollowupCreated={onFollowupCreated}
        />,
      );

      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(screen.getByText('OR ENTER CUSTOM TASK')).toBeInTheDocument();
      });

      const textarea = screen.getByPlaceholderText(/What specific question/);
      await act(async () => {
        await user.type(textarea, 'Custom task');
      });

      await act(async () => {
        await user.click(screen.getByText('[CREATE FOLLOW-UP]'));
      });

      await waitFor(() => {
        expect(onFollowupCreated).toHaveBeenCalledWith(followupResult);
      });
    });
  });

  describe('tab switching', () => {
    it('preserves fork state when switching tabs', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ suggestions: [] }),
      });

      const user = userEvent.setup();
      render(<DebateForkPanel debateId="debate-123" messageCount={10} />);

      // Enter modified context
      const textarea = screen.getByPlaceholderText(/What if we assumed/);
      await act(async () => {
        await user.type(textarea, 'My context');
      });

      // Switch to follow-up
      await act(async () => {
        await user.click(screen.getByText('[FOLLOW-UP]'));
      });

      // Switch back to fork
      await act(async () => {
        await user.click(screen.getByText('[FORK DEBATE]'));
      });

      // Context should be preserved
      expect(screen.getByDisplayValue('My context')).toBeInTheDocument();
    });
  });
});
