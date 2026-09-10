import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ErrorBoundary } from '@/components/ErrorBoundary';

// Component that throws an error
const ThrowError = ({ shouldThrow }: { shouldThrow: boolean }) => {
  if (shouldThrow) {
    throw new Error('Test error message');
  }
  return <div>No error</div>;
};

// Component that throws a named error
const ThrowNamedError = () => {
  const error = new Error('Custom named error');
  error.name = 'CustomError';
  throw error;
};

describe('ErrorBoundary', () => {
  // Suppress console.error for cleaner test output
  const originalError = console.error;
  beforeAll(() => {
    console.error = jest.fn();
  });
  afterAll(() => {
    console.error = originalError;
  });

  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div>Child content</div>
      </ErrorBoundary>,
    );

    expect(screen.getByText('Child content')).toBeInTheDocument();
  });

  it('catches errors and displays error UI', () => {
    render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('RUNTIME ERROR')).toBeInTheDocument();
    expect(screen.getByText('Test error message')).toBeInTheDocument();
  });

  it('displays error name', () => {
    render(
      <ErrorBoundary>
        <ThrowNamedError />
      </ErrorBoundary>,
    );

    expect(screen.getByText(/CustomError/)).toBeInTheDocument();
  });

  it('shows reset button', () => {
    render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText(/RESET_COMPONENT/)).toBeInTheDocument();
  });

  it('resets error state when reset button clicked', async () => {
    const { rerender } = render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>,
    );

    // Error UI should be visible
    expect(screen.getByText('RUNTIME ERROR')).toBeInTheDocument();

    // Re-render with non-throwing child
    rerender(
      <ErrorBoundary>
        <ThrowError shouldThrow={false} />
      </ErrorBoundary>,
    );

    // Click reset after swapping to non-throwing child
    fireEvent.click(screen.getByText(/RESET_COMPONENT/));

    // Should show normal content
    await waitFor(() => {
      expect(screen.getByText('No error')).toBeInTheDocument();
    });
    expect(screen.queryByText('RUNTIME ERROR')).not.toBeInTheDocument();
  });

  it('uses custom fallback when provided', () => {
    const customFallback = (error: Error, reset: () => void) => (
      <div>
        <span>Custom fallback: {error.message}</span>
        <button onClick={reset}>Custom reset</button>
      </div>
    );

    render(
      <ErrorBoundary fallback={customFallback}>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText(/Custom fallback/)).toBeInTheDocument();
    expect(screen.getByText('Custom reset')).toBeInTheDocument();
    // Default UI should not be present
    expect(screen.queryByText('RUNTIME ERROR')).not.toBeInTheDocument();
  });

  it('passes reset function to custom fallback', () => {
    const _resetMock = jest.fn();
    let capturedReset: (() => void) | null = null;

    const customFallback = (error: Error, reset: () => void) => {
      capturedReset = reset;
      return <div>Custom error UI</div>;
    };

    render(
      <ErrorBoundary fallback={customFallback}>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(capturedReset).toBeDefined();
    expect(typeof capturedReset).toBe('function');
  });

  it('logs error to console', () => {
    render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(console.error).toHaveBeenCalled();
  });

  it('displays stack trace snippet', () => {
    const errorWithStack = new Error('Error with stack');
    errorWithStack.stack = `Error: Error with stack
    at Component (file.tsx:10:5)
    at render (react.js:100:1)
    at mount (react.js:200:1)`;

    const ThrowWithStack = () => {
      throw errorWithStack;
    };

    render(
      <ErrorBoundary>
        <ThrowWithStack />
      </ErrorBoundary>,
    );

    // Should show part of the stack
    expect(screen.getByText(/at Component/)).toBeInTheDocument();
  });
});

describe('ErrorBoundary nested errors', () => {
  const originalError = console.error;
  beforeAll(() => {
    console.error = jest.fn();
  });
  afterAll(() => {
    console.error = originalError;
  });

  it('can have multiple ErrorBoundary components', () => {
    const NestedThrowError = () => {
      throw new Error('Nested error');
    };

    render(
      <ErrorBoundary>
        <div>Outer content</div>
        <ErrorBoundary>
          <NestedThrowError />
        </ErrorBoundary>
      </ErrorBoundary>,
    );

    // Outer content should still render
    expect(screen.getByText('Outer content')).toBeInTheDocument();
    // Inner error boundary should catch the error
    expect(screen.getByText('RUNTIME ERROR')).toBeInTheDocument();
  });
});
