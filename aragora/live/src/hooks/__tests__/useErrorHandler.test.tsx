import { renderHook, act } from '@testing-library/react';
import { useErrorHandler } from '../useErrorHandler';
import { ToastProvider } from '@/context/ToastContext';
import React from 'react';

// Mock the toast context
const mockShowError = jest.fn();

jest.mock('@/context/ToastContext', () => ({
  ...jest.requireActual('@/context/ToastContext'),
  useToastContext: () => ({
    showError: mockShowError,
    showToast: jest.fn(),
    showSuccess: jest.fn(),
    clearToasts: jest.fn(),
  }),
}));

// Wrapper for hooks that need context
const _wrapper = ({ children }: { children: React.ReactNode }) => (
  <ToastProvider>{children}</ToastProvider>
);

describe('useErrorHandler', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('handleError', () => {
    it('shows toast notification by default', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('Test error'));
      });

      expect(mockShowError).toHaveBeenCalledWith('Test error', 5000);
    });

    it('uses custom message when provided', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('Test error'), {
          customMessage: 'Custom error message',
        });
      });

      expect(mockShowError).toHaveBeenCalledWith('Custom error message', 5000);
    });

    it('respects showToast: false option', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('Test error'), { showToast: false });
      });

      expect(mockShowError).not.toHaveBeenCalled();
    });

    it('classifies network errors correctly', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('Network request failed'));
      });

      expect(mockShowError).toHaveBeenCalledWith(
        'Connection failed. Please check your network and try again.',
        5000,
      );
    });

    it('classifies auth errors correctly', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('401 Unauthorized'));
      });

      expect(mockShowError).toHaveBeenCalledWith(
        'Authentication required. Please log in and try again.',
        5000,
      );
    });

    it('classifies server errors correctly', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('500 Internal Server Error'));
      });

      expect(mockShowError).toHaveBeenCalledWith(
        'Server error. Our team has been notified. Please try again later.',
        5000,
      );
    });

    it('classifies timeout errors correctly', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('Request timeout'));
      });

      expect(mockShowError).toHaveBeenCalledWith('Request timed out. Please try again.', 5000);
    });

    it('handles non-Error objects', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError('String error');
      });

      expect(mockShowError).toHaveBeenCalledWith('An unexpected error occurred.', 5000);
    });

    it('stores last error', () => {
      const { result } = renderHook(() => useErrorHandler());
      const testError = new Error('Test error');

      act(() => {
        result.current.handleError(testError);
      });

      expect(result.current.lastError?.message).toBe('Test error');
    });

    it('clears last error', () => {
      const { result } = renderHook(() => useErrorHandler());

      act(() => {
        result.current.handleError(new Error('Test error'));
      });

      expect(result.current.lastError).not.toBeNull();

      act(() => {
        result.current.clearError();
      });

      expect(result.current.lastError).toBeNull();
    });
  });

  describe('handleAsync', () => {
    it('returns result on success', async () => {
      const { result } = renderHook(() => useErrorHandler());

      let asyncResult: string | undefined;
      await act(async () => {
        asyncResult = await result.current.handleAsync(() => Promise.resolve('success'));
      });

      expect(asyncResult).toBe('success');
      expect(mockShowError).not.toHaveBeenCalled();
    });

    it('calls onSuccess callback on success', async () => {
      const { result } = renderHook(() => useErrorHandler());
      const onSuccess = jest.fn();

      await act(async () => {
        await result.current.handleAsync(() => Promise.resolve('success'), { onSuccess });
      });

      expect(onSuccess).toHaveBeenCalledWith('success');
    });

    it('returns undefined and shows toast on error', async () => {
      const { result } = renderHook(() => useErrorHandler());

      let asyncResult: string | undefined = 'should-be-undefined';
      await act(async () => {
        asyncResult = await result.current.handleAsync(() =>
          Promise.reject(new Error('Async error')),
        );
      });

      expect(asyncResult).toBeUndefined();
      expect(mockShowError).toHaveBeenCalledWith('Async error', 5000);
    });

    it('does not call onSuccess on error', async () => {
      const { result } = renderHook(() => useErrorHandler());
      const onSuccess = jest.fn();

      await act(async () => {
        await result.current.handleAsync(() => Promise.reject(new Error('Async error')), {
          onSuccess,
        });
      });

      expect(onSuccess).not.toHaveBeenCalled();
    });
  });

  describe('withErrorHandling', () => {
    it('wraps function and returns result on success', async () => {
      const { result } = renderHook(() => useErrorHandler());
      const originalFn = jest.fn().mockResolvedValue('success');

      let wrappedFn: typeof originalFn;
      act(() => {
        wrappedFn = result.current.withErrorHandling(originalFn);
      });

      let wrappedResult: string | undefined;
      await act(async () => {
        wrappedResult = await wrappedFn!();
      });

      expect(wrappedResult).toBe('success');
      expect(originalFn).toHaveBeenCalled();
    });

    it('handles errors from wrapped function', async () => {
      const { result } = renderHook(() => useErrorHandler());
      const originalFn = jest.fn().mockRejectedValue(new Error('Wrapped error'));

      let wrappedFn: typeof originalFn;
      act(() => {
        wrappedFn = result.current.withErrorHandling(originalFn);
      });

      let wrappedResult: string | undefined = 'should-be-undefined';
      await act(async () => {
        wrappedResult = await wrappedFn!();
      });

      expect(wrappedResult).toBeUndefined();
      expect(mockShowError).toHaveBeenCalledWith('Wrapped error', 5000);
    });

    it('passes arguments to wrapped function', async () => {
      const { result } = renderHook(() => useErrorHandler());
      const originalFn = jest.fn().mockResolvedValue('success');

      let wrappedFn: (a: string, b: number) => Promise<string | undefined>;
      act(() => {
        wrappedFn = result.current.withErrorHandling(originalFn);
      });

      await act(async () => {
        await wrappedFn!('arg1', 42);
      });

      expect(originalFn).toHaveBeenCalledWith('arg1', 42);
    });
  });
});
