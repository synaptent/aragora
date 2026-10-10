import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import GlobalError from '../global-error';

const mockSentry = { loaded: jest.fn(), captureException: jest.fn() };
jest.mock('@sentry/nextjs', () => {
  mockSentry.loaded();
  return { captureException: (error: unknown) => mockSentry.captureException(error) };
});
const mockReporter = { capture: jest.fn(() => true), flush: jest.fn() };
jest.mock('@/lib/crash-reporter', () => ({ getCrashReporter: () => mockReporter }));

const TEST_DSN = 'http://public@localhost:3141/1';
const savedDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

function setDsn(value: string | undefined) {
  if (value === undefined) delete process.env.NEXT_PUBLIC_SENTRY_DSN;
  else process.env.NEXT_PUBLIC_SENTRY_DSN = value;
}

function expectLocalReport(error: Error) {
  expect(mockReporter.capture).toHaveBeenCalledTimes(1);
  expect(mockReporter.capture.mock.calls[0]).toEqual([
    error,
    { componentName: 'next-global-error-boundary' },
  ]);
  expect((mockReporter.capture.mock.calls[0] as unknown[])[0]).toBe(error);
  expect(mockReporter.flush).toHaveBeenCalledTimes(1);
}

beforeEach(() => {
  jest.clearAllMocks();
  setDsn(undefined);
  // The boundary renders its own <html>/<body>, which React reports as a nesting warning here.
  jest.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  jest.restoreAllMocks();
  setDsn(savedDsn);
});

test('global error boundary uses only the local crash reporter without a public DSN', async () => {
  const error = new Error('disabled');
  const reset = jest.fn();
  render(<GlobalError error={error} reset={reset} />);

  expect(screen.getByText('ARAGORA // CRITICAL ERROR')).toBeInTheDocument();
  expectLocalReport(error);
  await Promise.resolve();
  expect(mockSentry.loaded).not.toHaveBeenCalled();
  expect(mockSentry.captureException).not.toHaveBeenCalled();

  fireEvent.click(screen.getByText(/RETRY/));
  expect(reset).toHaveBeenCalledTimes(1);
});

test('global error boundary reports the exact error to Sentry and locally with a DSN', async () => {
  setDsn(TEST_DSN);
  const error = new Error('enabled');
  render(<GlobalError error={error} reset={jest.fn()} />);

  await waitFor(() => expect(mockSentry.captureException).toHaveBeenCalledTimes(1));
  expect(mockSentry.captureException.mock.calls[0]).toHaveLength(1);
  expect(mockSentry.captureException.mock.calls[0][0]).toBe(error);
  expectLocalReport(error);
});

test('global error boundary keeps the recovery UI when Sentry capture fails', async () => {
  setDsn(TEST_DSN);
  mockSentry.captureException.mockImplementationOnce(() => {
    throw new Error('sdk unavailable');
  });
  const error = new Error('boom');
  render(<GlobalError error={error} reset={jest.fn()} />);

  await waitFor(() => expect(mockSentry.captureException).toHaveBeenCalledTimes(1));
  expect(screen.getByText('ARAGORA // CRITICAL ERROR')).toBeInTheDocument();
  expectLocalReport(error);
});
