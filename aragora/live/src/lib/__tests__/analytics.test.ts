import { capture } from '../analytics';

const mockCapture = jest.fn();
const mockLoadPosthog = jest.fn();
jest.mock('posthog-js', () => {
  mockLoadPosthog();
  return { __esModule: true, default: { capture: mockCapture } };
});

describe('analytics.capture', () => {
  const originalKey = process.env.NEXT_PUBLIC_POSTHOG_KEY;

  beforeEach(() => {
    jest.clearAllMocks();
    delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
  });

  afterAll(() => {
    if (originalKey === undefined) delete process.env.NEXT_PUBLIC_POSTHOG_KEY;
    else process.env.NEXT_PUBLIC_POSTHOG_KEY = originalKey;
  });

  it('does not import the SDK or send without a key', async () => {
    await capture('example', { safe: true });
    expect(mockLoadPosthog).not.toHaveBeenCalled();
    expect(mockCapture).not.toHaveBeenCalled();
  });

  it('drops email, password, token and other sensitive keys before sending', async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = 'phc_test';
    const props = {
      email: 'private@example.test',
      password: 'private-password',
      token: 'private-token',
      clientSecret: 'private-secret',
      Authorization: 'private-auth',
      Cookie: 'private-cookie',
      apiKey: 'private-key',
      count: 3,
      nested: { email: 'nested@example.test', label: 'safe' },
      items: [{ accessToken: 'private-access', ok: true }],
    };
    await capture('example', props);
    expect(mockCapture).toHaveBeenCalledWith('example', {
      count: 3,
      nested: { label: 'safe' },
      items: [{ ok: true }],
    });
    const sent = mockCapture.mock.calls[0][1];
    expect(sent).not.toHaveProperty('email');
    expect(sent).not.toHaveProperty('password');
    expect(sent).not.toHaveProperty('token');
    expect(props.email).toBe('private@example.test');
  });

  it('allows omitted props and nonsensitive primitive values', async () => {
    process.env.NEXT_PUBLIC_POSTHOG_KEY = 'phc_test';
    await capture('empty');
    await capture('values', { nothing: null, values: [1, 'safe', false] });
    expect(mockCapture).toHaveBeenCalledWith('empty', {});
    expect(mockCapture).toHaveBeenCalledWith('values', {
      nothing: null,
      values: [1, 'safe', false],
    });
  });
});
