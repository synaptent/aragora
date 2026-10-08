/**
 * Tests for UserParticipation component
 *
 * Note: This is a placeholder test file. To run these tests, you would need to:
 * 1. Install Jest and React Testing Library: npm install --save-dev jest @testing-library/react @testing-library/jest-dom
 * 2. Configure Jest in package.json or jest.config.js
 * 3. Add test script to package.json
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { UserParticipation } from '../src/components/UserParticipation';
import type { StreamEvent } from '../src/types/events';

const mockEvents: StreamEvent[] = [
  {
    type: 'agent_message',
    data: { role: 'proposer', content: 'Proposal A: Add feature X', agent: 'Agent1' },
    timestamp: Date.now(),
    round: 1,
    agent: 'Agent1'
  },
  {
    type: 'agent_message',
    data: { role: 'proposer', content: 'Proposal B: Add feature Y', agent: 'Agent2' },
    timestamp: Date.now(),
    round: 1,
    agent: 'Agent2'
  }
];

describe('UserParticipation', () => {
  const mockOnVote = jest.fn();
  const mockOnSuggest = jest.fn();
  const mockOnAck = jest.fn();
  const mockOnError = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders vote options from agent messages', () => {
    render(
      <UserParticipation
        events={mockEvents}
        onVote={mockOnVote}
        onSuggest={mockOnSuggest}
        onAck={mockOnAck}
        onError={mockOnError}
      />
    );

    expect(screen.getByText('Vote on Proposals')).toBeInTheDocument();
    expect(screen.getByText('Agent1')).toBeInTheDocument();
    expect(screen.getByText('Agent2')).toBeInTheDocument();
  });

  it('calls onVote with selected choice when vote is submitted', () => {
    render(
      <UserParticipation
        events={mockEvents}
        onVote={mockOnVote}
        onSuggest={mockOnSuggest}
        onAck={mockOnAck}
        onError={mockOnError}
      />
    );

    const radioButton = screen.getByDisplayValue('Agent1');
    fireEvent.click(radioButton);

    const submitButton = screen.getByText('Submit Vote');
    fireEvent.click(submitButton);

    // onVote now receives (choice, intensity) where intensity defaults to 5
    expect(mockOnVote).toHaveBeenCalledWith('Agent1', expect.any(Number));
  });

  it('calls onSuggest with trimmed suggestion when suggestion is submitted', () => {
    render(
      <UserParticipation
        events={mockEvents}
        onVote={mockOnVote}
        onSuggest={mockOnSuggest}
        onAck={mockOnAck}
        onError={mockOnError}
      />
    );

    const textarea = screen.getByPlaceholderText('Share your thoughts or suggest an improvement...');
    fireEvent.change(textarea, { target: { value: '  Great idea!  ' } });

    const submitButton = screen.getByText('Suggest');
    fireEvent.click(submitButton);

    expect(mockOnSuggest).toHaveBeenCalledWith('Great idea!');
  });

  it('shows success state after ack callback', async () => {
    let ackCallback: (msgType: string) => void = () => {};

    mockOnAck.mockImplementation((callback) => {
      ackCallback = callback;
      return () => {};
    });

    await act(async () => {
      render(
        <UserParticipation
          events={mockEvents}
          onVote={mockOnVote}
          onSuggest={mockOnSuggest}
          onAck={mockOnAck}
          onError={mockOnError}
        />
      );
    });

    // Submit a vote
    const radioButton = screen.getByDisplayValue('Agent1');
    await act(async () => {
      fireEvent.click(radioButton);
    });
    const submitButton = screen.getByText('Submit Vote');
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Simulate ack
    await act(async () => {
      ackCallback('user_vote');
    });

    await waitFor(() => {
      expect(screen.getByText('Vote Submitted ✓')).toBeInTheDocument();
    });
  });

  it('shows error state after error callback', async () => {
    let errorCallback: (message: string) => void = () => {};

    mockOnError.mockImplementation((callback) => {
      errorCallback = callback;
      return () => {};
    });

    await act(async () => {
      render(
        <UserParticipation
          events={mockEvents}
          onVote={mockOnVote}
          onSuggest={mockOnSuggest}
          onAck={mockOnAck}
          onError={mockOnError}
        />
      );
    });

    // Submit a suggestion
    const textarea = screen.getByPlaceholderText('Share your thoughts or suggest an improvement...');
    await act(async () => {
      fireEvent.change(textarea, { target: { value: 'Test suggestion' } });
    });
    const submitButton = screen.getByText('Suggest');
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Simulate error (non-rate-limited error shows "Failed")
    await act(async () => {
      errorCallback('Server error occurred.');
    });

    await waitFor(() => {
      expect(screen.getByText('Failed')).toBeInTheDocument();
    });
  });

  it('prevents multiple submissions while pending', () => {
    render(
      <UserParticipation
        events={mockEvents}
        onVote={mockOnVote}
        onSuggest={mockOnSuggest}
        onAck={mockOnAck}
        onError={mockOnError}
      />
    );

    const radioButton = screen.getByDisplayValue('Agent1');
    fireEvent.click(radioButton);

    const submitButton = screen.getByText('Submit Vote');
    fireEvent.click(submitButton);

    // Button should be disabled immediately
    expect(submitButton).toBeDisabled();
    expect(mockOnVote).toHaveBeenCalledTimes(1);
  });
});
