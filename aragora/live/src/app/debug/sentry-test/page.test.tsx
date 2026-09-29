import { render, screen } from '@testing-library/react';
import SentryTestPage from './page';

describe('Sentry test trigger', () => {
  const originalDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

  afterEach(() => {
    jest.restoreAllMocks();
    window.history.replaceState({}, '', '/');
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
  });
});
