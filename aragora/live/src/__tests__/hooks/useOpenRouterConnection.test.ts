import { act, renderHook, waitFor } from '@testing-library/react';
import { useOpenRouterConnection } from '@/hooks/useOpenRouterConnection';
import { getStoredProviderKeys, storeProviderKeys } from '@/lib/provider-keys';
import { fetchKeyInfo, startOpenRouterAuth, type OpenRouterKeyInfo } from '@/lib/openrouter-pkce';

jest.mock('@/lib/provider-keys', () => ({
  getStoredProviderKeys: jest.fn(),
  storeProviderKeys: jest.fn(),
}));

jest.mock('@/lib/openrouter-pkce', () => ({
  fetchKeyInfo: jest.fn(),
  startOpenRouterAuth: jest.fn(),
}));

const mockGetStoredProviderKeys = getStoredProviderKeys as jest.MockedFunction<
  typeof getStoredProviderKeys
>;
const mockStoreProviderKeys = storeProviderKeys as jest.MockedFunction<typeof storeProviderKeys>;
const mockFetchKeyInfo = fetchKeyInfo as jest.MockedFunction<typeof fetchKeyInfo>;
const mockStartOpenRouterAuth = startOpenRouterAuth as jest.MockedFunction<
  typeof startOpenRouterAuth
>;

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useOpenRouterConnection', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetStoredProviderKeys.mockReturnValue({});
    mockFetchKeyInfo.mockResolvedValue(null);
  });

  it('keeps the latest key info when an earlier request resolves later', async () => {
    const firstRequest = deferred<OpenRouterKeyInfo | null>();
    const secondRequest = deferred<OpenRouterKeyInfo | null>();
    const latestInfo: OpenRouterKeyInfo = {
      label: 'latest',
      limit: 10,
      limitRemaining: 8,
      usage: 2,
      rateLimit: null,
    };

    mockGetStoredProviderKeys.mockReturnValue({ openrouter: 'sk-or-test' });
    mockFetchKeyInfo
      .mockReturnValueOnce(firstRequest.promise)
      .mockReturnValueOnce(secondRequest.promise);

    const { result } = renderHook(() => useOpenRouterConnection());

    await waitFor(() => expect(mockFetchKeyInfo).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.refreshKeyInfo();
    });

    await waitFor(() => expect(mockFetchKeyInfo).toHaveBeenCalledTimes(2));

    await act(async () => {
      secondRequest.resolve(latestInfo);
      await secondRequest.promise;
    });

    await waitFor(() => expect(result.current.keyInfo).toEqual(latestInfo));

    await act(async () => {
      firstRequest.resolve({
        label: 'stale',
        limit: 5,
        limitRemaining: 1,
        usage: 4,
        rateLimit: null,
      });
      await firstRequest.promise;
    });

    expect(result.current.keyInfo).toEqual(latestInfo);
  });

  it('logs and clears key info when refresh rejects unexpectedly', async () => {
    const debugSpy = jest.spyOn(console, 'debug').mockImplementation(() => {});
    const initialInfo: OpenRouterKeyInfo = {
      label: 'connected',
      limit: 20,
      limitRemaining: 15,
      usage: 5,
      rateLimit: null,
    };

    mockGetStoredProviderKeys.mockReturnValue({ openrouter: 'sk-or-test' });
    mockFetchKeyInfo.mockResolvedValueOnce(initialInfo).mockRejectedValueOnce(new Error('boom'));

    const { result } = renderHook(() => useOpenRouterConnection());

    await waitFor(() => expect(result.current.keyInfo).toEqual(initialInfo));

    act(() => {
      result.current.refreshKeyInfo();
    });

    await waitFor(() => expect(result.current.keyInfo).toBeNull());
    expect(debugSpy).toHaveBeenCalledWith(
      'Failed to refresh OpenRouter key info',
      expect.any(Error),
    );

    debugSpy.mockRestore();
  });

  it('invalidates in-flight requests on disconnect', async () => {
    const pendingRequest = deferred<OpenRouterKeyInfo | null>();

    mockGetStoredProviderKeys.mockReturnValue({ openrouter: 'sk-or-test' });
    mockFetchKeyInfo.mockReturnValueOnce(pendingRequest.promise);

    const { result } = renderHook(() => useOpenRouterConnection());

    await waitFor(() => expect(result.current.isConnected).toBe(true));
    expect(mockFetchKeyInfo).toHaveBeenCalledTimes(1);

    mockGetStoredProviderKeys.mockReturnValue({ openrouter: 'sk-or-test' });

    act(() => {
      result.current.disconnect();
    });

    await act(async () => {
      pendingRequest.resolve({
        label: 'stale',
        limit: 10,
        limitRemaining: 5,
        usage: 5,
        rateLimit: null,
      });
      await pendingRequest.promise;
    });

    expect(mockStoreProviderKeys).toHaveBeenCalledWith({});
    expect(result.current.isConnected).toBe(false);
    expect(result.current.keyInfo).toBeNull();
  });

  it('starts the PKCE flow with the callback URL derived from the current origin', () => {
    const { result } = renderHook(() => useOpenRouterConnection());

    act(() => {
      result.current.connect();
    });

    expect(mockStartOpenRouterAuth).toHaveBeenCalledWith(
      `${window.location.origin}/openrouter/callback/`,
    );
  });
});
