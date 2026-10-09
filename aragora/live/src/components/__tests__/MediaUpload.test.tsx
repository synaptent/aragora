import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import { MediaUpload } from '../MediaUpload';

jest.mock('../VoiceRecorder', () => ({ VoiceRecorder: () => null }));
jest.mock('../YouTubeInput', () => ({ YouTubeInput: () => null }));

const API = 'http://backend.test';
const mockFetch = global.fetch as jest.Mock;

function hasAuthorization(init?: RequestInit): boolean {
  const headers = (init?.headers ?? {}) as Record<string, string>;
  return Object.keys(headers).some((name) => name.toLowerCase() === 'authorization');
}

/** Backend stand-in that refuses unauthenticated uploads, like the real documents route. */
function mockUploadBackend() {
  mockFetch.mockImplementation(async (input: string, init?: RequestInit) => {
    if (!hasAuthorization(init)) {
      return { ok: false, status: 401, json: async () => ({ error: 'Authentication required' }) };
    }
    if (String(input).endsWith('/api/documents/upload')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          document: { id: 'doc-a', filename: 'policy.md', word_count: 3, preview: 'Org A policy' },
        }),
      };
    }
    return { ok: true, status: 200, json: async () => ({ job_id: 'job-a', status: 'completed', text: 'hello' }) };
  });
}

function dropFile(name: string, type: string) {
  const file = new File(['Org A policy'], name, { type });
  fireEvent.drop(screen.getByRole('button', { name: /Upload a file/ }), { dataTransfer: { files: [file] } });
}

describe('MediaUpload authentication', () => {
  beforeEach(() => mockUploadBackend());
  afterEach(() => clearTestSession());

  it('sends the session token with the document upload and reports the uploaded document', async () => {
    storeTestSession();
    const onDocumentsChange = jest.fn();
    render(<MediaUpload apiBase={API} onDocumentsChange={onDocumentsChange} />);

    dropFile('policy.md', 'text/markdown');

    await waitFor(() => expect(onDocumentsChange).toHaveBeenCalledTimes(1));
    expect(authHeaderOf(mockFetch, `${API}/api/documents/upload`, 'POST')).toBe(`Bearer ${TEST_SESSION_TOKEN}`);
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect(Object.keys(init.headers as Record<string, string>)).toEqual(['Authorization']);
    expect(screen.getByText('policy.md')).toBeInTheDocument();
  });

  it('does not report a successful upload without a session', async () => {
    const onDocumentsChange = jest.fn();
    render(<MediaUpload apiBase={API} onDocumentsChange={onDocumentsChange} />);

    dropFile('policy.md', 'text/markdown');

    expect(await screen.findByText('Authentication required')).toBeInTheDocument();
    expect(authHeaderOf(mockFetch, `${API}/api/documents/upload`, 'POST')).toBeUndefined();
    expect(onDocumentsChange).not.toHaveBeenCalled();
    expect(screen.queryByText('policy.md')).not.toBeInTheDocument();
  });

  it('sends the session token with audio uploads for transcription', async () => {
    storeTestSession();
    const onTranscriptionsChange = jest.fn();
    render(<MediaUpload apiBase={API} onTranscriptionsChange={onTranscriptionsChange} />);

    dropFile('memo.mp3', 'audio/mpeg');

    await waitFor(() => expect(onTranscriptionsChange).toHaveBeenCalledTimes(1));
    expect(authHeaderOf(mockFetch, `${API}/api/transcription/audio`, 'POST')).toBe(`Bearer ${TEST_SESSION_TOKEN}`);
  });
});
