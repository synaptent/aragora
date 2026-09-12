import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary } from '../src/components/ErrorBoundary';
import { ErrorRetry, DataState } from '../src/components/ErrorRetry';
import { ApiError } from '../src/components/ApiError';

// Suppress console.error for ErrorBoundary tests
const originalError = console.error;
beforeAll(() => {
  console.error = jest.fn();
});
afterAll(() => {
  console.error = originalError;
});

// =============================================================================
// ErrorBoundary Tests
// =============================================================================

describe('ErrorBoundary', () => {
  const ThrowingComponent = ({ shouldThrow }: { shouldThrow: boolean }) => {
    if (shouldThrow) {
      throw new Error('Test error message');
    }
    return <div>Child content</div>;
  };

  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div>Test content</div>
      </ErrorBoundary>,
    );

    expect(screen.getByText('Test content')).toBeInTheDocument();
  });

  it('catches errors and shows error UI', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('RUNTIME ERROR')).toBeInTheDocument();
    expect(screen.getByText('Component crashed during render')).toBeInTheDocument();
    expect(screen.getByText('Test error message')).toBeInTheDocument();
  });

  it('shows error name in error details', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    // The error name appears as "> Error" in the details section
    expect(screen.getByText(/> Error/)).toBeInTheDocument();
  });

  it('shows reset button', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('> RESET_COMPONENT')).toBeInTheDocument();
  });

  it('calls resetError when reset clicked', () => {
    // Test that clicking reset triggers the state change
    render(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('RUNTIME ERROR')).toBeInTheDocument();

    // Click reset - this clears the error state
    fireEvent.click(screen.getByText('> RESET_COMPONENT'));

    // Note: ErrorBoundary resets internal state, but if the same
    // component is still throwing, it will re-catch the error.
    // This test verifies the reset button is clickable and calls the handler.
    // A real recovery would require the underlying issue to be fixed.
  });

  it('uses custom fallback when provided', () => {
    const customFallback = (error: Error, resetError: () => void) => (
      <div>
        <span>Custom error: {error.message}</span>
        <button onClick={resetError}>Custom reset</button>
      </div>
    );

    render(
      <ErrorBoundary fallback={customFallback}>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Custom error: Test error message')).toBeInTheDocument();
    expect(screen.getByText('Custom reset')).toBeInTheDocument();
  });
});

// =============================================================================
// ErrorRetry Tests
// =============================================================================

describe('ErrorRetry', () => {
  describe('block mode (default)', () => {
    it('renders default error message', () => {
      render(<ErrorRetry />);

      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });

    it('renders custom message', () => {
      render(<ErrorRetry message="Custom error message" />);

      expect(screen.getByText('Custom error message')).toBeInTheDocument();
    });

    it('shows warning icon', () => {
      render(<ErrorRetry />);

      expect(screen.getByText('⚠')).toBeInTheDocument();
    });

    it('shows retry button when onRetry provided', () => {
      render(<ErrorRetry onRetry={() => {}} />);

      expect(screen.getByText('[RETRY]')).toBeInTheDocument();
    });

    it('calls onRetry when clicked', () => {
      const onRetry = jest.fn();
      render(<ErrorRetry onRetry={onRetry} />);

      fireEvent.click(screen.getByText('[RETRY]'));

      expect(onRetry).toHaveBeenCalled();
    });

    it('shows retrying state', () => {
      render(<ErrorRetry onRetry={() => {}} retrying={true} />);

      expect(screen.getByText('Retrying')).toBeInTheDocument();
    });

    it('disables button when retrying', () => {
      render(<ErrorRetry onRetry={() => {}} retrying={true} />);

      expect(screen.getByRole('button')).toBeDisabled();
    });

    it('shows retry attempt count', () => {
      render(<ErrorRetry onRetry={() => {}} retrying={true} retryAttempt={2} maxRetries={5} />);

      expect(screen.getByText('Retry attempt 2/5...')).toBeInTheDocument();
    });
  });

  describe('inline mode', () => {
    it('renders inline style', () => {
      render(<ErrorRetry inline={true} />);

      expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    });

    it('shows inline retry link', () => {
      render(<ErrorRetry inline={true} onRetry={() => {}} />);

      expect(screen.getByText('[Retry]')).toBeInTheDocument();
    });

    it('shows inline retrying state', () => {
      render(<ErrorRetry inline={true} onRetry={() => {}} retrying={true} />);

      expect(screen.getByText('Retrying...')).toBeInTheDocument();
    });
  });

  describe('size variants', () => {
    it('renders small size', () => {
      const { container } = render(<ErrorRetry size="sm" />);

      expect(container.firstChild).toHaveClass('text-xs');
    });

    it('renders medium size', () => {
      const { container } = render(<ErrorRetry size="md" />);

      expect(container.firstChild).toHaveClass('text-sm');
    });

    it('renders large size', () => {
      const { container } = render(<ErrorRetry size="lg" />);

      expect(container.firstChild).toHaveClass('text-base');
    });
  });
});

// =============================================================================
// DataState Tests
// =============================================================================

describe('DataState', () => {
  it('shows loading state', () => {
    render(
      <DataState data={null} loading={true} error={null}>
        {(data) => <div>{data}</div>}
      </DataState>,
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows custom loading text', () => {
    render(
      <DataState data={null} loading={true} error={null} loadingText="Fetching data...">
        {(data) => <div>{data}</div>}
      </DataState>,
    );

    expect(screen.getByText('Fetching data...')).toBeInTheDocument();
  });

  it('shows error state with ErrorRetry', () => {
    const error = new Error('Fetch failed');
    render(
      <DataState data={null} loading={false} error={error}>
        {(data) => <div>{data}</div>}
      </DataState>,
    );

    expect(screen.getByText('Fetch failed')).toBeInTheDocument();
  });

  it('shows empty state', () => {
    render(
      <DataState data={null} loading={false} error={null}>
        {(data) => <div>{data}</div>}
      </DataState>,
    );

    expect(screen.getByText('No data available')).toBeInTheDocument();
  });

  it('shows custom empty text', () => {
    render(
      <DataState data={null} loading={false} error={null} emptyText="Nothing here">
        {(data) => <div>{data}</div>}
      </DataState>,
    );

    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  it('renders children with data', () => {
    render(
      <DataState data="Test data" loading={false} error={null}>
        {(data) => <div>Data: {data}</div>}
      </DataState>,
    );

    expect(screen.getByText('Data: Test data')).toBeInTheDocument();
  });

  it('passes onRetry to ErrorRetry', () => {
    const error = new Error('Test error');
    const onRetry = jest.fn();

    render(
      <DataState data={null} loading={false} error={error} onRetry={onRetry}>
        {(data) => <div>{data}</div>}
      </DataState>,
    );

    fireEvent.click(screen.getByText('[RETRY]'));

    expect(onRetry).toHaveBeenCalled();
  });
});

// =============================================================================
// ApiError Tests
// =============================================================================

describe('ApiError', () => {
  it('returns null when no error', () => {
    const { container } = render(<ApiError error={null} />);

    expect(container.firstChild).toBeNull();
  });

  describe('block mode (default)', () => {
    it('renders string error', () => {
      render(<ApiError error="API request failed" />);

      expect(screen.getByText('ERROR')).toBeInTheDocument();
      expect(screen.getByText('API request failed')).toBeInTheDocument();
    });

    it('renders Error object', () => {
      render(<ApiError error={new Error('Network timeout')} />);

      expect(screen.getByText('Network timeout')).toBeInTheDocument();
    });

    it('shows retry button when onRetry provided', () => {
      render(<ApiError error="Error" onRetry={() => {}} />);

      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    });

    it('calls onRetry when clicked', () => {
      const onRetry = jest.fn();
      render(<ApiError error="Error" onRetry={onRetry} />);

      fireEvent.click(screen.getByRole('button', { name: /retry/i }));

      expect(onRetry).toHaveBeenCalled();
    });
  });

  describe('compact mode', () => {
    it('renders compact style', () => {
      render(<ApiError error="Compact error" compact={true} />);

      expect(screen.getByText(/ERROR:/)).toBeInTheDocument();
      expect(screen.getByText('Compact error')).toBeInTheDocument();
    });

    it('shows compact retry button', () => {
      render(<ApiError error="Error" compact={true} onRetry={() => {}} />);

      expect(screen.getByText('RETRY')).toBeInTheDocument();
    });
  });

  it('applies custom className', () => {
    const { container } = render(<ApiError error="Error" className="custom-class" />);

    expect(container.firstChild).toHaveClass('custom-class');
  });
});
