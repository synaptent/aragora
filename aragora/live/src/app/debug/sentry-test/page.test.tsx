import { render, screen } from '@testing-library/react';
import SentryTestPage from './page';

const mockNotFound = jest.fn(() => {
  throw new Error('NEXT_HTTP_ERROR_FALLBACK;404');
});
jest.mock('next/navigation', () => ({ notFound: () => mockNotFound() }));

function setNodeEnv(value: string | undefined) {
  const env = process.env as Record<string, string | undefined>;
  if (value === undefined) delete env.NODE_ENV;
  else env.NODE_ENV = value;
}

describe('Sentry test trigger', () => {
  const originalDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  const originalNodeEnv = process.env.NODE_ENV;

  beforeEach(() => {
    mockNotFound.mockClear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
    window.history.replaceState({}, '', '/');
    setNodeEnv(originalNodeEnv);
    if (originalDsn === undefined) delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    else process.env.NEXT_PUBLIC_SENTRY_DSN = originalDsn;
  });

  it('does not throw without a public DSN even with boom=1', () => {
    delete process.env.NEXT_PUBLIC_SENTRY_DSN;
    window.history.replaceState({}, '', '/debug/sentry-test/?boom=1');
    render(<SentryTestPage />);
    expect(screen.getByText(/Sentry test: add/)).toBeInTheDocument();
  });

  it('does not throw without boom=1 even with a public DSN', () => {
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    render(<SentryTestPage />);
    expect(screen.getByText(/Sentry test: add/)).toBeInTheDocument();
  });

  it('throws the documented client error only when both gates are enabled', () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    window.history.replaceState({}, '', '/debug/sentry-test/?boom=1');
    expect(() => render(<SentryTestPage />)).toThrow('Aragora Live Sentry test error');
    expect(mockNotFound).not.toHaveBeenCalled();
  });

  it('calls notFound before the trigger in production', () => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    setNodeEnv('production');
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    window.history.replaceState({}, '', '/debug/sentry-test/?boom=1');
    expect(() => render(<SentryTestPage />)).toThrow('NEXT_HTTP_ERROR_FALLBACK;404');
    expect(mockNotFound).toHaveBeenCalled();
    expect(screen.queryByText(/Sentry test: add/)).not.toBeInTheDocument();
  });

  it.each(['development', 'test'])('keeps the trigger and skips notFound in %s', (nodeEnv) => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    setNodeEnv(nodeEnv);
    process.env.NEXT_PUBLIC_SENTRY_DSN = 'http://public@localhost:3141/1';
    render(<SentryTestPage />);
    expect(screen.getByText(/Sentry test: add/)).toBeInTheDocument();
    window.history.replaceState({}, '', '/debug/sentry-test/?boom=1');
    expect(() => render(<SentryTestPage />)).toThrow('Aragora Live Sentry test error');
    expect(mockNotFound).not.toHaveBeenCalled();
  });
});
