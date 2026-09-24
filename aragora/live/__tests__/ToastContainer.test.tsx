import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ToastContainer } from '@/components/ToastContainer';
import type { Toast } from '@/hooks/useToast';

describe('ToastContainer', () => {
  const mockOnRemove = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('returns null when no toasts', () => {
    const { container } = render(<ToastContainer toasts={[]} onRemove={mockOnRemove} />);

    expect(container.firstChild).toBeNull();
  });

  it('renders a single toast', () => {
    const toasts: Toast[] = [{ id: '1', type: 'info', message: 'Test message' }];

    render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

    expect(screen.getByText('Test message')).toBeInTheDocument();
  });

  it('renders multiple toasts', () => {
    const toasts: Toast[] = [
      { id: '1', type: 'info', message: 'First message' },
      { id: '2', type: 'error', message: 'Second message' },
      { id: '3', type: 'success', message: 'Third message' },
    ];

    render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

    expect(screen.getByText('First message')).toBeInTheDocument();
    expect(screen.getByText('Second message')).toBeInTheDocument();
    expect(screen.getByText('Third message')).toBeInTheDocument();
  });

  describe('Toast types', () => {
    it('renders error toast with correct icon', () => {
      const toasts: Toast[] = [{ id: '1', type: 'error', message: 'Error message' }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      expect(screen.getByText('✕')).toBeInTheDocument();
    });

    it('renders success toast with correct icon', () => {
      const toasts: Toast[] = [{ id: '1', type: 'success', message: 'Success message' }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      expect(screen.getByText('✓')).toBeInTheDocument();
    });

    it('renders warning toast with correct icon', () => {
      const toasts: Toast[] = [{ id: '1', type: 'warning', message: 'Warning message' }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      expect(screen.getByText('⚠')).toBeInTheDocument();
    });

    it('renders info toast with correct icon', () => {
      const toasts: Toast[] = [{ id: '1', type: 'info', message: 'Info message' }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      expect(screen.getByText('ℹ')).toBeInTheDocument();
    });
  });

  describe('Toast interactions', () => {
    it('calls onRemove when close button clicked', async () => {
      const toasts: Toast[] = [{ id: 'toast-1', type: 'info', message: 'Test message' }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      const closeButton = screen.getByLabelText('Close');
      fireEvent.click(closeButton);

      // Wait for animation timeout
      act(() => {
        jest.advanceTimersByTime(200);
      });

      expect(mockOnRemove).toHaveBeenCalledWith('toast-1');
    });

    it('has accessible close button', () => {
      const toasts: Toast[] = [{ id: '1', type: 'info', message: 'Test message' }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      expect(screen.getByLabelText('Close')).toBeInTheDocument();
    });
  });

  describe('Toast positioning', () => {
    it('has fixed positioning', () => {
      const toasts: Toast[] = [{ id: '1', type: 'info', message: 'Test message' }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      const container = screen.getByRole('region', { name: /notifications/i });
      expect(container).toHaveClass('fixed');
    });
  });

  describe('Toast auto-dismiss', () => {
    it('applies exit animation before duration expires', () => {
      const toasts: Toast[] = [{ id: '1', type: 'info', message: 'Test message', duration: 3000 }];

      render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

      // Advance to just before exit animation (3000 - 300 = 2700ms)
      act(() => {
        jest.advanceTimersByTime(2700);
      });

      // The component should start exit animation
      const toastElement = screen.getByRole('status');
      expect(toastElement).toHaveClass('opacity-0');
    });
  });
});

describe('ToastContainer edge cases', () => {
  const mockOnRemove = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('handles long messages', () => {
    const longMessage = 'A'.repeat(500);
    const toasts: Toast[] = [{ id: '1', type: 'info', message: longMessage }];

    render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

    expect(screen.getByText(longMessage)).toBeInTheDocument();
  });

  it('handles messages with special characters', () => {
    const specialMessage = '<script>alert("xss")</script>';
    const toasts: Toast[] = [{ id: '1', type: 'info', message: specialMessage }];

    render(<ToastContainer toasts={toasts} onRemove={mockOnRemove} />);

    // Should be rendered as text, not HTML
    expect(screen.getByText(specialMessage)).toBeInTheDocument();
  });

  it('handles rapid additions and removals', () => {
    const { rerender } = render(<ToastContainer toasts={[]} onRemove={mockOnRemove} />);

    // Add toasts
    rerender(
      <ToastContainer
        toasts={[{ id: '1', type: 'info', message: 'Message 1' }]}
        onRemove={mockOnRemove}
      />,
    );

    expect(screen.getByText('Message 1')).toBeInTheDocument();

    // Remove and add different toast
    rerender(
      <ToastContainer
        toasts={[{ id: '2', type: 'success', message: 'Message 2' }]}
        onRemove={mockOnRemove}
      />,
    );

    expect(screen.queryByText('Message 1')).not.toBeInTheDocument();
    expect(screen.getByText('Message 2')).toBeInTheDocument();
  });
});
