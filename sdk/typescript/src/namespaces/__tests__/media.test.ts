import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { MediaAPI } from '../media';

interface MockClient {
  request: Mock;
}

describe('MediaAPI Namespace', () => {
  let api: MediaAPI;
  let mockClient: MockClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
    };
    api = new MediaAPI(mockClient as any);
  });

  it('rejects audio conversion when no public route exists', async () => {
    await expect(
      api.convertAudio('audio_123', {
        targetFormat: 'aac',
        bitrate: 128,
      })
    ).rejects.toThrow('/api/v1/media/audio/{audioId}/convert');

    expect(mockClient.request).not.toHaveBeenCalled();
  });

  it('rejects transcription lookup when no public route exists', async () => {
    await expect(api.getTranscription('audio_123')).rejects.toThrow(
      '/api/v1/media/audio/{audioId}/transcription'
    );

    expect(mockClient.request).not.toHaveBeenCalled();
  });
});
