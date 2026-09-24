/**
 * Tests for ToastContext
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ToastProvider, useToastContext } from '../ToastContext';

// Mock the useToast hook
jest.mock('@/hooks/useToast', () => ({
  useToast: () => ({
    toasts: [],
    showToast: jest.fn(),
    showError: jest.fn(),
    showSuccess: jest.fn(),
    removeToast: jest.fn(),
    clearToasts: jest.fn(),
  }),
}));

// Mock ToastContainer
jest.mock('@/components/ToastContainer', () => ({
  ToastContainer: ({
    toasts,
    onRemove: _onRemove,
  }: {
    toasts: unknown[];
    onRemove: (id: string) => void;
  }) => (
    <div data-testid="toast-container">
      {toasts &&
        (toasts as { id: string; message: string }[]).map((t) => <div key={t.id}>{t.message}</div>)}
    </div>
  ),
}));

// Test component that uses the toast context
function TestConsumer() {
  const { showToast, showError, showSuccess, clearToasts } = useToastContext();
  return (
    <div>
      <button onClick={() => showToast('Test message')}>Show Toast</button>
      <button onClick={() => showError('Error message')}>Show Error</button>
      <button onClick={() => showSuccess('Success message')}>Show Success</button>
      <button onClick={() => clearToasts()}>Clear</button>
    </div>
  );
}

describe('ToastContext', () => {
  describe('ToastProvider', () => {
    it('renders children', () => {
      render(
        <ToastProvider>
          <div data-testid="child">Child content</div>
        </ToastProvider>,
      );

      expect(screen.getByTestId('child')).toBeInTheDocument();
    });

    it('renders ToastContainer', () => {
      render(
        <ToastProvider>
          <div>Test</div>
        </ToastProvider>,
      );

      expect(screen.getByTestId('toast-container')).toBeInTheDocument();
    });

    it('provides toast functions to consumers', () => {
      render(
        <ToastProvider>
          <TestConsumer />
        </ToastProvider>,
      );

      // Verify all buttons render (functions are accessible)
      expect(screen.getByText('Show Toast')).toBeInTheDocument();
      expect(screen.getByText('Show Error')).toBeInTheDocument();
      expect(screen.getByText('Show Success')).toBeInTheDocument();
      expect(screen.getByText('Clear')).toBeInTheDocument();
    });

    it('calls showToast when button clicked', () => {
      render(
        <ToastProvider>
          <TestConsumer />
        </ToastProvider>,
      );

      // Click should not throw
      fireEvent.click(screen.getByText('Show Toast'));
    });

    it('calls showError when button clicked', () => {
      render(
        <ToastProvider>
          <TestConsumer />
        </ToastProvider>,
      );

      fireEvent.click(screen.getByText('Show Error'));
    });

    it('calls showSuccess when button clicked', () => {
      render(
        <ToastProvider>
          <TestConsumer />
        </ToastProvider>,
      );

      fireEvent.click(screen.getByText('Show Success'));
    });

    it('calls clearToasts when button clicked', () => {
      render(
        <ToastProvider>
          <TestConsumer />
        </ToastProvider>,
      );

      fireEvent.click(screen.getByText('Clear'));
    });
  });

  describe('useToastContext', () => {
    it('throws error when used outside provider', () => {
      // Suppress console.error for this test
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();

      expect(() => {
        render(<TestConsumer />);
      }).toThrow('useToastContext must be used within a ToastProvider');

      consoleSpy.mockRestore();
    });
  });
});
