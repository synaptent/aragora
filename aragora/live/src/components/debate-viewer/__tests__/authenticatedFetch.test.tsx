import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import { TricksterAlert } from '../TricksterAlert';
import { RhetoricalPanel } from '../RhetoricalPanel';
import { EvidenceLinkGraph } from '../EvidenceLinkGraph';
import { AudioDownloadSection } from '../AudioDownloadSection';

const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
const mockFetch = global.fetch as jest.Mock;

describe('debate viewer panels send the session token', () => {
  beforeEach(() => {
    storeTestSession();
    mockFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
  });

  afterEach(() => clearTestSession());

  it('TricksterAlert loads trickster analysis with the token', async () => {
    render(<TricksterAlert debateId="debate-a" />);

    await waitFor(() => expect(authHeaderOf(mockFetch, '/api/debates/debate-a/trickster')).toBe(bearer));
  });

  it('RhetoricalPanel loads rhetorical analysis with the token', async () => {
    render(<RhetoricalPanel debateId="debate-a" />);

    await waitFor(() => expect(authHeaderOf(mockFetch, '/api/debates/debate-a/rhetorical')).toBe(bearer));
  });

  it('EvidenceLinkGraph loads evidence with the token', async () => {
    render(<EvidenceLinkGraph debateId="debate-a" />);

    await waitFor(() => expect(authHeaderOf(mockFetch, '/api/debates/debate-a/evidence')).toBe(bearer));
  });

  it('AudioDownloadSection checks for audio and requests generation with the token', async () => {
    mockFetch.mockImplementation(async (_input: string, init?: RequestInit) =>
      init?.method === 'HEAD'
        ? { ok: false, status: 404 }
        : { ok: true, status: 200, json: async () => ({ error: 'stub' }) },
    );
    render(<AudioDownloadSection debateId="debate-a" />);

    fireEvent.click(await screen.findByRole('button', { name: '[GENERATE MP3]' }));

    await waitFor(() =>
      expect(authHeaderOf(mockFetch, '/api/debates/debate-a/broadcast', 'POST')).toBe(bearer),
    );
    expect(authHeaderOf(mockFetch, '/audio/debate-a.mp3', 'HEAD')).toBe(bearer);
  });
});
