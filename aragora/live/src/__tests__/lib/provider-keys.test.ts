import {
  PROVIDER_KEYS_STORAGE_KEY,
  getProviderKeyHeaders,
  getStoredProviderKeys,
  storeProviderKeys,
} from '@/lib/provider-keys';

describe('provider-keys', () => {
  const localStorageMock = (() => {
    let store: Record<string, string> = {};
    return {
      getItem: jest.fn((key: string) => store[key] ?? null),
      setItem: jest.fn((key: string, value: string) => {
        store[key] = value;
      }),
      removeItem: jest.fn((key: string) => {
        delete store[key];
      }),
      clear: jest.fn(() => {
        store = {};
      }),
    };
  })();

  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { value: localStorageMock });
    localStorageMock.clear();
    jest.clearAllMocks();
  });

  it('stores and reloads provider keys', () => {
    const keys = { openrouter: 'sk-or-test', openai: 'sk-test' };

    storeProviderKeys(keys);

    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      PROVIDER_KEYS_STORAGE_KEY,
      JSON.stringify(keys),
    );
    expect(getStoredProviderKeys()).toEqual(keys);
  });

  it('warns and returns an empty object for malformed storage', () => {
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    localStorageMock.getItem.mockReturnValue('{broken-json');

    expect(getStoredProviderKeys()).toEqual({});
    expect(warnSpy).toHaveBeenCalledWith(
      'Failed to parse stored provider keys from localStorage.',
      expect.any(Error),
    );

    warnSpy.mockRestore();
  });

  it('builds provider headers for known configured keys', () => {
    localStorageMock.getItem.mockReturnValue(
      JSON.stringify({ openrouter: 'sk-or-test', openai: 'sk-test', unknown: 'ignored' }),
    );

    expect(getProviderKeyHeaders()).toEqual({
      'X-Provider-Key-openai': 'sk-test',
      'X-Provider-Key-openrouter': 'sk-or-test',
    });
  });
});
