/**
 * Tests for API utility functions
 *
 * Tests cover:
 * - apiFetch URL resolution (relative paths, absolute URLs, base paths)
 * - apiFetch error handling (HTTP errors, network errors, empty responses)
 * - apiFetchSafe error wrapping
 * - HTTP method wrappers (apiGet, apiPost, apiPut, apiDelete)
 * - Content-type handling
 */

import { apiFetch, apiFetchSafe, apiGet, apiPost, apiPut, apiDelete } from '../api';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('API Utilities', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  describe('apiFetch', () => {
    describe('URL resolution', () => {
      it('uses absolute URLs as-is', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ data: 'test' }),
        });

        await apiFetch('https://external.api.com/endpoint');

        expect(mockFetch).toHaveBeenCalledWith(
          'https://external.api.com/endpoint',
          expect.any(Object),
        );
      });

      it('prepends base URL to /api/ paths', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ data: 'test' }),
        });

        await apiFetch('/api/debates');

        expect(mockFetch).toHaveBeenCalledWith('/api/debates', expect.any(Object));
      });

      it('prepends base URL to other relative paths', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ data: 'test' }),
        });

        await apiFetch('/health');

        expect(mockFetch).toHaveBeenCalledWith('/health', expect.any(Object));
      });

      it('adds leading slash to bare paths', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ data: 'test' }),
        });

        await apiFetch('debates');

        expect(mockFetch).toHaveBeenCalledWith('/debates', expect.any(Object));
      });

      it('uses custom baseUrl when provided', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ data: 'test' }),
        });

        await apiFetch('/api/debates', { baseUrl: 'https://custom.api.com' });

        expect(mockFetch).toHaveBeenCalledWith(
          'https://custom.api.com/api/debates',
          expect.any(Object),
        );
      });

      it('uses the saved runtime backend when one is selected', async () => {
        localStorage.setItem('aragora-backend', 'production');
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({ data: 'test' }),
        });

        await apiFetch('/api/debates');

        expect(mockFetch).toHaveBeenCalledWith(
          'https://api.aragora.ai/api/debates',
          expect.any(Object),
        );
      });
    });

    describe('headers', () => {
      it('sets Content-Type to application/json by default', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({}),
        });

        await apiFetch('/api/test');

        expect(mockFetch).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
          }),
        );
      });

      it('allows overriding headers', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({}),
        });

        await apiFetch('/api/test', { headers: { Authorization: 'Bearer token123' } });

        expect(mockFetch).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            headers: expect.objectContaining({
              'Content-Type': 'application/json',
              Authorization: 'Bearer token123',
            }),
          }),
        );
      });
    });

    describe('error handling', () => {
      it('throws error with status and message on HTTP error', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: false,
          status: 404,
          statusText: 'Not Found',
          text: async () => 'Resource not found',
        });

        await expect(apiFetch('/api/missing')).rejects.toThrow(
          'API Error (404): Resource not found',
        );
      });

      it('uses statusText when text() fails', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: false,
          status: 500,
          statusText: 'Internal Server Error',
          text: async () => {
            throw new Error('Cannot parse body');
          },
        });

        await expect(apiFetch('/api/error')).rejects.toThrow(
          'API Error (500): Internal Server Error',
        );
      });

      it('propagates network errors', async () => {
        mockFetch.mockRejectedValueOnce(new Error('Network failure'));

        await expect(apiFetch('/api/test')).rejects.toThrow('Network failure');
      });
    });

    describe('response handling', () => {
      it('parses JSON response', async () => {
        const responseData = { id: 1, name: 'Test' };
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => responseData,
        });

        const result = await apiFetch<{ id: number; name: string }>('/api/test');

        expect(result).toEqual(responseData);
      });

      it('returns empty object for non-JSON content type', async () => {
        mockFetch.mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'text/plain' }),
        });

        const result = await apiFetch('/api/text');

        expect(result).toEqual({});
      });

      it('returns empty object for empty content-type', async () => {
        mockFetch.mockResolvedValueOnce({ ok: true, headers: new Headers() });

        const result = await apiFetch('/api/empty');

        expect(result).toEqual({});
      });
    });
  });

  describe('apiFetchSafe', () => {
    it('returns data on success', async () => {
      const responseData = { success: true };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => responseData,
      });

      const result = await apiFetchSafe('/api/test');

      expect(result).toEqual({ data: responseData });
      expect(result.error).toBeUndefined();
    });

    it('returns error on HTTP error', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        text: async () => 'Invalid input',
      });

      const result = await apiFetchSafe('/api/test');

      expect(result.data).toBeUndefined();
      expect(result.error).toBe('API Error (400): Invalid input');
    });

    it('returns error on network failure', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Connection refused'));

      const result = await apiFetchSafe('/api/test');

      expect(result.data).toBeUndefined();
      expect(result.error).toBe('Connection refused');
    });

    it('handles non-Error exceptions', async () => {
      mockFetch.mockRejectedValueOnce('String error');

      const result = await apiFetchSafe('/api/test');

      expect(result.error).toBe('String error');
    });
  });

  describe('apiGet', () => {
    it('makes GET request', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ items: [] }),
      });

      await apiGet('/api/items');

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ method: 'GET' }),
      );
    });

    it('passes through options', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({}),
      });

      await apiGet('/api/test', { headers: { 'X-Custom': 'value' } });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({ 'X-Custom': 'value' }),
        }),
      );
    });
  });

  describe('apiPost', () => {
    it('makes POST request with JSON body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ id: 1 }),
      });

      const body = { name: 'New Item' };
      await apiPost('/api/items', body);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ method: 'POST', body: JSON.stringify(body) }),
      );
    });

    it('handles undefined body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({}),
      });

      await apiPost('/api/trigger');

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ method: 'POST', body: undefined }),
      );
    });
  });

  describe('apiPut', () => {
    it('makes PUT request with JSON body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ updated: true }),
      });

      const body = { name: 'Updated Item' };
      await apiPut('/api/items/1', body);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ method: 'PUT', body: JSON.stringify(body) }),
      );
    });
  });

  describe('apiDelete', () => {
    it('makes DELETE request', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ deleted: true }),
      });

      await apiDelete('/api/items/1');

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ method: 'DELETE' }),
      );
    });
  });
});
