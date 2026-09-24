import { renderHook, act } from '@testing-library/react';
import { useToast, ToastType } from '@/hooks/useToast';

describe('useToast', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('initial state', () => {
    it('should start with empty toasts array', () => {
      const { result } = renderHook(() => useToast());

      expect(result.current.toasts).toEqual([]);
    });
  });

  describe('showToast', () => {
    it('should add a toast to the array', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Test message');
      });

      expect(result.current.toasts).toHaveLength(1);
      expect(result.current.toasts[0].message).toBe('Test message');
    });

    it('should default to info type', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Info toast');
      });

      expect(result.current.toasts[0].type).toBe('info');
    });

    it('should accept custom type', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Error toast', 'error');
      });

      expect(result.current.toasts[0].type).toBe('error');
    });

    it('should accept custom duration', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Custom duration', 'info', 10000);
      });

      expect(result.current.toasts[0].duration).toBe(10000);
    });

    it('should generate unique IDs for each toast', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Toast 1');
        result.current.showToast('Toast 2');
        result.current.showToast('Toast 3');
      });

      const ids = result.current.toasts.map((t) => t.id);
      const uniqueIds = new Set(ids);
      expect(uniqueIds.size).toBe(3);
    });

    it('should auto-remove toast after duration', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Auto-remove', 'info', 3000);
      });

      expect(result.current.toasts).toHaveLength(1);

      act(() => {
        jest.advanceTimersByTime(3000);
      });

      expect(result.current.toasts).toHaveLength(0);
    });

    it('should use default duration of 5000ms', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Default duration');
      });

      expect(result.current.toasts).toHaveLength(1);

      act(() => {
        jest.advanceTimersByTime(4999);
      });

      expect(result.current.toasts).toHaveLength(1);

      act(() => {
        jest.advanceTimersByTime(1);
      });

      expect(result.current.toasts).toHaveLength(0);
    });
  });

  describe('showError', () => {
    it('should create error toast', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showError('Error occurred');
      });

      expect(result.current.toasts[0].type).toBe('error');
      expect(result.current.toasts[0].message).toBe('Error occurred');
    });

    it('should accept custom duration', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showError('Error', 10000);
      });

      expect(result.current.toasts[0].duration).toBe(10000);
    });
  });

  describe('showSuccess', () => {
    it('should create success toast', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showSuccess('Success!');
      });

      expect(result.current.toasts[0].type).toBe('success');
      expect(result.current.toasts[0].message).toBe('Success!');
    });

    it('should use 3000ms default duration for success', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showSuccess('Quick success');
      });

      expect(result.current.toasts).toHaveLength(1);

      act(() => {
        jest.advanceTimersByTime(3000);
      });

      expect(result.current.toasts).toHaveLength(0);
    });
  });

  describe('removeToast', () => {
    it('should remove specific toast by ID', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Toast 1');
        result.current.showToast('Toast 2');
        result.current.showToast('Toast 3');
      });

      const toastToRemove = result.current.toasts[1];

      act(() => {
        result.current.removeToast(toastToRemove.id);
      });

      expect(result.current.toasts).toHaveLength(2);
      expect(result.current.toasts.map((t) => t.message)).toEqual(['Toast 1', 'Toast 3']);
    });

    it('should clear timeout when removing toast', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Will be removed', 'info', 5000);
      });

      const toastId = result.current.toasts[0].id;

      act(() => {
        result.current.removeToast(toastId);
      });

      // Advance timers past the original duration
      act(() => {
        jest.advanceTimersByTime(10000);
      });

      // Toast should already be gone, no errors should occur
      expect(result.current.toasts).toHaveLength(0);
    });

    it('should handle removing non-existent toast gracefully', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Existing toast');
      });

      expect(() => {
        act(() => {
          result.current.removeToast('non-existent-id');
        });
      }).not.toThrow();

      expect(result.current.toasts).toHaveLength(1);
    });
  });

  describe('clearToasts', () => {
    it('should remove all toasts', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Toast 1');
        result.current.showToast('Toast 2');
        result.current.showToast('Toast 3');
      });

      expect(result.current.toasts).toHaveLength(3);

      act(() => {
        result.current.clearToasts();
      });

      expect(result.current.toasts).toHaveLength(0);
    });

    it('should clear all pending timeouts', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Toast 1', 'info', 5000);
        result.current.showToast('Toast 2', 'info', 10000);
      });

      act(() => {
        result.current.clearToasts();
      });

      // Advance past all durations
      act(() => {
        jest.advanceTimersByTime(15000);
      });

      // No errors should occur from orphaned timeouts
      expect(result.current.toasts).toHaveLength(0);
    });
  });

  describe('cleanup on unmount', () => {
    it('should clear all timeouts on unmount', () => {
      const { result, unmount } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('Toast 1', 'info', 5000);
        result.current.showToast('Toast 2', 'info', 10000);
      });

      unmount();

      // Advance timers after unmount - no errors should occur
      expect(() => {
        act(() => {
          jest.advanceTimersByTime(15000);
        });
      }).not.toThrow();
    });
  });

  describe('toast types', () => {
    const types: ToastType[] = ['success', 'error', 'warning', 'info'];

    types.forEach((type) => {
      it(`should support ${type} toast type`, () => {
        const { result } = renderHook(() => useToast());

        act(() => {
          result.current.showToast(`${type} message`, type);
        });

        expect(result.current.toasts[0].type).toBe(type);
      });
    });
  });

  describe('multiple toasts ordering', () => {
    it('should maintain FIFO order', () => {
      const { result } = renderHook(() => useToast());

      act(() => {
        result.current.showToast('First');
        result.current.showToast('Second');
        result.current.showToast('Third');
      });

      expect(result.current.toasts.map((t) => t.message)).toEqual(['First', 'Second', 'Third']);
    });
  });
});
