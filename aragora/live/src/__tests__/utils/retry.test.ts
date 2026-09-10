/**
 * Tests for retry utilities
 */

import { retry, fetchWithRetry, isRetryableError } from '@/utils/retry';

describe('retry utilities', () => {
  describe('retry', () => {
    it('returns result on first success', async () => {
      const fn = jest.fn().mockResolvedValue('success');

      const result = await retry(fn);

      expect(result).toBe('success');
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it('retries on failure and succeeds with short delays', async () => {
      const fn = jest.fn().mockRejectedValueOnce(new Error('fail 1')).mockResolvedValue('success');

      const result = await retry(fn, { maxRetries: 2, baseDelayMs: 1, maxDelayMs: 1 });

      expect(result).toBe('success');
      expect(fn).toHaveBeenCalledTimes(2);
    }, 10000);

    it('throws after max retries', async () => {
      const fn = jest.fn().mockRejectedValue(new Error('always fails'));

      await expect(retry(fn, { maxRetries: 2, baseDelayMs: 1, maxDelayMs: 1 })).rejects.toThrow(
        'always fails',
      );

      expect(fn).toHaveBeenCalledTimes(3); // initial + 2 retries
    }, 10000);

    it('calls onRetry callback on each retry', async () => {
      const fn = jest.fn().mockRejectedValue(new Error('fail'));
      const onRetry = jest.fn();

      try {
        await retry(fn, { maxRetries: 2, baseDelayMs: 1, maxDelayMs: 1, onRetry });
      } catch {
        // Expected
      }

      expect(onRetry).toHaveBeenCalledTimes(2);
      expect(onRetry).toHaveBeenNthCalledWith(1, 1, expect.any(Error));
      expect(onRetry).toHaveBeenNthCalledWith(2, 2, expect.any(Error));
    }, 10000);

    it('uses default options', async () => {
      const fn = jest.fn().mockResolvedValue('ok');

      const result = await retry(fn);

      expect(result).toBe('ok');
    });

    it('converts non-Error throws to Error', async () => {
      const fn = jest.fn().mockRejectedValue('string error');

      await expect(retry(fn, { maxRetries: 0 })).rejects.toThrow('string error');
    });
  });

  describe('fetchWithRetry', () => {
    const mockFetch = jest.fn();

    beforeEach(() => {
      global.fetch = mockFetch;
      mockFetch.mockReset();
    });

    it('returns response on success', async () => {
      const mockResponse = { ok: true, status: 200 };
      mockFetch.mockResolvedValue(mockResponse);

      const result = await fetchWithRetry('https://api.example.com/data');

      expect(result).toBe(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith('https://api.example.com/data', expect.anything());
    });

    it('passes init options to fetch', async () => {
      const mockResponse = { ok: true, status: 200 };
      mockFetch.mockResolvedValue(mockResponse);
      const init = { method: 'POST', body: 'data' };

      await fetchWithRetry('https://api.example.com/data', init);

      expect(mockFetch).toHaveBeenCalledWith('https://api.example.com/data', init);
    });

    it('retries on 5xx server errors', async () => {
      mockFetch
        .mockResolvedValueOnce({ ok: false, status: 500 })
        .mockResolvedValueOnce({ ok: false, status: 503 })
        .mockResolvedValue({ ok: true, status: 200 });

      const result = await fetchWithRetry('https://api.example.com', undefined, {
        maxRetries: 3,
        baseDelayMs: 1,
        maxDelayMs: 1,
      });

      expect(result.status).toBe(200);
      expect(mockFetch).toHaveBeenCalledTimes(3);
    }, 10000);

    it('does not retry on 4xx client errors', async () => {
      const mockResponse = { ok: false, status: 404 };
      mockFetch.mockResolvedValue(mockResponse);

      const result = await fetchWithRetry('https://api.example.com');

      expect(result.status).toBe(404);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('does not retry on 401 unauthorized', async () => {
      const mockResponse = { ok: false, status: 401 };
      mockFetch.mockResolvedValue(mockResponse);

      const result = await fetchWithRetry('https://api.example.com');

      expect(result.status).toBe(401);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('retries on network errors', async () => {
      mockFetch
        .mockRejectedValueOnce(new TypeError('Failed to fetch'))
        .mockResolvedValue({ ok: true, status: 200 });

      const result = await fetchWithRetry('https://api.example.com', undefined, {
        maxRetries: 1,
        baseDelayMs: 1,
        maxDelayMs: 1,
      });

      expect(result.status).toBe(200);
      expect(mockFetch).toHaveBeenCalledTimes(2);
    }, 10000);
  });

  describe('isRetryableError', () => {
    it('returns true for TypeError (network error)', () => {
      expect(isRetryableError(new TypeError('Failed to fetch'))).toBe(true);
    });

    it('returns true for network error message', () => {
      expect(isRetryableError(new Error('Network error occurred'))).toBe(true);
    });

    it('returns true for timeout error message', () => {
      expect(isRetryableError(new Error('Request timeout'))).toBe(true);
    });

    it('returns true for server error message', () => {
      expect(isRetryableError(new Error('Server error: 500'))).toBe(true);
    });

    it('returns true for failed to fetch message', () => {
      expect(isRetryableError(new Error('Failed to fetch data'))).toBe(true);
    });

    it('returns false for regular errors', () => {
      expect(isRetryableError(new Error('Invalid input'))).toBe(false);
    });

    it('returns false for non-Error values', () => {
      expect(isRetryableError('string')).toBe(false);
      expect(isRetryableError(null)).toBe(false);
      expect(isRetryableError(undefined)).toBe(false);
      expect(isRetryableError(123)).toBe(false);
    });

    it('is case insensitive', () => {
      expect(isRetryableError(new Error('NETWORK ERROR'))).toBe(true);
      expect(isRetryableError(new Error('TIMEOUT'))).toBe(true);
    });
  });
});
