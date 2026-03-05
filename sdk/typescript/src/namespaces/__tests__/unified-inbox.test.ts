import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { UnifiedInboxAPI } from '../unified-inbox';

interface MockClient {
  request: Mock;
}

describe('UnifiedInboxAPI', () => {
  let mockClient: MockClient;
  let api: UnifiedInboxAPI;

  beforeEach(() => {
    mockClient = {
      request: vi.fn().mockResolvedValue({}),
    };
    api = new UnifiedInboxAPI(mockClient as any);
  });

  it('maps autoDebate to inbox message debate route', async () => {
    await api.autoDebate('msg/1');

    expect(mockClient.request).toHaveBeenCalledWith(
      'POST',
      '/api/v1/inbox/messages/msg%2F1/debate'
    );
  });

  it('calls debateMessage without json body when request is empty', async () => {
    await api.debateMessage('msg/1', {});

    expect(mockClient.request).toHaveBeenCalledWith(
      'POST',
      '/api/v1/inbox/messages/msg%2F1/debate'
    );
  });

  it('calls debateMessage with json body when options are provided', async () => {
    await api.debateMessage('msg/1', { rounds: 4, consensus: 'majority' });

    expect(mockClient.request).toHaveBeenCalledWith(
      'POST',
      '/api/v1/inbox/messages/msg%2F1/debate',
      { json: { rounds: 4, consensus: 'majority' } }
    );
  });
});
