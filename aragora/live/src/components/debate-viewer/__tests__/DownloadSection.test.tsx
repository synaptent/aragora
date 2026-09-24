import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// Mock config
jest.mock('@/config', () => ({ API_BASE_URL: 'http://localhost:8000' }));

// Mock AudioDownloadSection
jest.mock('../AudioDownloadSection', () => ({
  AudioDownloadSection: () => <div data-testid="audio-download-section">Audio</div>,
}));

import { DownloadSection } from '../DownloadSection';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch as typeof fetch;

// Mock URL methods
const mockCreateObjectURL = jest.fn(() => 'blob:mock-url');
const mockRevokeObjectURL = jest.fn();
URL.createObjectURL = mockCreateObjectURL;
URL.revokeObjectURL = mockRevokeObjectURL;

describe('DownloadSection', () => {
  const debateId = 'debate-123';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('incomplete debate', () => {
    it('shows message when debate is not completed', () => {
      render(<DownloadSection debateId={debateId} isCompleted={false} />);
      expect(screen.getByText('[EXPORTS AVAILABLE AFTER DEBATE COMPLETES]')).toBeInTheDocument();
    });

    it('does not show export buttons when incomplete', () => {
      render(<DownloadSection debateId={debateId} isCompleted={false} />);
      expect(screen.queryByText('[JSON]')).not.toBeInTheDocument();
    });
  });

  describe('completed debate', () => {
    it('renders section header', () => {
      render(<DownloadSection debateId={debateId} />);
      expect(screen.getByText('Download Transcript')).toBeInTheDocument();
    });

    it('renders all export format buttons', () => {
      render(<DownloadSection debateId={debateId} />);
      expect(screen.getByText('[JSON]')).toBeInTheDocument();
      expect(screen.getByText('[CSV]')).toBeInTheDocument();
      expect(screen.getByText('[Markdown]')).toBeInTheDocument();
      expect(screen.getByText('[Text]')).toBeInTheDocument();
      expect(screen.getByText('[HTML]')).toBeInTheDocument();
    });

    it('renders audio section', () => {
      render(<DownloadSection debateId={debateId} />);
      expect(screen.getByText('Audio Podcast')).toBeInTheDocument();
      expect(screen.getByTestId('audio-download-section')).toBeInTheDocument();
    });
  });

  describe('download functionality', () => {
    it('calls fetch with correct URL on download', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve('{"data": "test"}'),
      });

      render(<DownloadSection debateId={debateId} />);
      fireEvent.click(screen.getByText('[JSON]'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining(`/api/debates/${debateId}/export/json`),
        );
      });
    });

    it('shows loading state during download', async () => {
      let resolvePromise: (value: { ok: boolean; text: () => Promise<string> }) => void;
      mockFetch.mockReturnValueOnce(
        new Promise((resolve) => {
          resolvePromise = resolve;
        }),
      );

      render(<DownloadSection debateId={debateId} />);
      fireEvent.click(screen.getByText('[CSV]'));

      expect(screen.getByText('[CSV...]')).toBeInTheDocument();

      resolvePromise!({ ok: true, text: () => Promise.resolve('data') });

      await waitFor(() => {
        expect(screen.getByText('[CSV]')).toBeInTheDocument();
      });
    });
  });

  describe('error handling', () => {
    it('displays error message on failed response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ error: 'Server error' }),
      });

      render(<DownloadSection debateId={debateId} />);
      fireEvent.click(screen.getByText('[JSON]'));

      await waitFor(() => {
        expect(screen.getByText('Server error')).toBeInTheDocument();
      });
    });

    it('handles network errors', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network failure'));

      render(<DownloadSection debateId={debateId} />);
      fireEvent.click(screen.getByText('[HTML]'));

      await waitFor(() => {
        expect(screen.getByText('Network failure')).toBeInTheDocument();
      });
    });
  });
});
