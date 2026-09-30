import { render, screen, waitFor } from '@testing-library/react';
import ErrorBoundary from '../error';

const mockCaptureException = jest.fn();
const mockLoadSentry = jest.fn();
jest.mock('@sentry/nextjs', () => {
  mockLoadSentry();
  return { captureException: mockCaptureException };
});
jest.mock('@/lib/crash-reporter', () => ({
  getCrashReporter: () => ({ capture: jest.fn(() => false) }),
}));

describe('app error boundary Sentry reporting', () => {
  const originalKey = process.env.NEXT_PUBLIC_SENTRY_DSN;

  beforeEach(() => {
    jest.clearAllMocks();
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
    if (originalKey === undefined) delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    else process.env.NEXT_PUBLIC_SENTRY_DSN = originalKey;
  });

  it('renders the fallback without loading or calling Sentry when disabled', () => {
    render(<ErrorBoundary error={new Error('disabled')} reset={jest.fn()} />);
    expect(screen.getByText('SOMETHING WENT WRONG')).toBeInTheDocument();
    expect(mockLoadSentry).not.toHaveBeenCalled();
    expect(mockCaptureException).not.toHaveBeenCalled();
  });

  it('reports the original exception when the public DSN is configured', async () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    const error = new Error('enabled');
    render(<ErrorBoundary error={error} reset={jest.fn()} />);
    await waitFor(() => expect(mockCaptureException).toHaveBeenCalledWith(error));
  });
});
