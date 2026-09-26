/**
 * Tests for consent-gated telemetry (src/telemetry.ts).
 *
 * The all-on cases run the real @sentry/node and posthog-node SDKs with their
 * network layers replaced: Sentry gets a recording transport and PostHog a
 * recording fetch, so no request leaves the process.
 */

import { gunzipSync } from 'zlib';
import { ExtensionMode, env, resetMockVscode, setMockConfiguration } from './vscode.mock';
import { Telemetry, type TelemetryOptions } from '../telemetry';

const packageVersion: string = jest.requireActual<{ version: string }>(
  '../../package.json',
).version;

const SENTRY_DSN = 'https://public@o0.ingest.sentry.test/1';
const POSTHOG_KEY = 'phc_test_key';

type SentryModule = typeof import('@sentry/node');
type PostHogModule = typeof import('posthog-node');

interface SentryEnvelopeItem {
  type: string;
  payload: Record<string, unknown>;
}

interface PostHogBatch {
  api_key: string;
  batch: Array<{ event: string; distinct_id: string; properties: Record<string, unknown> }>;
}

/** Real SDK modules whose constructors and network layers are recorded. */
function recordingSdks() {
  const sentryActual = jest.requireActual<SentryModule>('@sentry/node');
  const posthogActual = jest.requireActual<PostHogModule>('posthog-node');

  const sentryClientOptions: Array<Record<string, unknown>> = [];
  const sentryItems: SentryEnvelopeItem[] = [];
  const posthogClients: Array<{ key: string; options: Record<string, unknown> }> = [];
  const posthogBatches: PostHogBatch[] = [];

  class RecordingNodeClient extends sentryActual.NodeClient {
    constructor(options: ConstructorParameters<typeof sentryActual.NodeClient>[0]) {
      sentryClientOptions.push(options as unknown as Record<string, unknown>);
      super(options);
    }
  }

  const recordingTransport = () => ({
    send: async (envelope: unknown) => {
      const [, items] = envelope as [unknown, Array<[{ type: string }, Record<string, unknown>]>];
      for (const [header, payload] of items) {
        sentryItems.push({ type: header.type, payload });
      }
      return { statusCode: 200 };
    },
    flush: async () => true,
  });

  const recordingFetch = async (
    _url: string,
    init: { headers: Record<string, string>; body?: unknown },
  ) => {
    const raw =
      init.headers['Content-Encoding'] === 'gzip'
        ? gunzipSync(Buffer.from(init.body as Uint8Array)).toString('utf8')
        : String(init.body);
    posthogBatches.push(JSON.parse(raw) as PostHogBatch);
    return { status: 200, text: async () => '{}', json: async () => ({}) };
  };

  class RecordingPostHog extends posthogActual.PostHog {
    constructor(key: string, options: ConstructorParameters<typeof posthogActual.PostHog>[1] = {}) {
      posthogClients.push({ key, options: options as Record<string, unknown> });
      super(key, { ...options, fetch: recordingFetch as never });
    }
  }

  const sentryModule = {
    ...sentryActual,
    NodeClient: RecordingNodeClient,
    makeNodeTransport: recordingTransport,
  };
  const posthogModule = { ...posthogActual, PostHog: RecordingPostHog };

  const loadSentry = jest.fn(() => sentryModule);
  const loadPostHog = jest.fn(() => posthogModule);

  return {
    loadSentry,
    loadPostHog,
    sentryClientOptions,
    sentryItems,
    posthogClients,
    posthogBatches,
  };
}

function allGatesOn(): void {
  env.isTelemetryEnabled = true;
  setMockConfiguration({
    'aragora.telemetry.enabled': true,
    'aragora.telemetry.sentryDsn': SENTRY_DSN,
    'aragora.telemetry.posthogKey': POSTHOG_KEY,
  });
}

function missingModule(name: string): () => never {
  return () => {
    const error = new Error(`Cannot find module '${name}'`) as NodeJS.ErrnoException;
    error.code = 'MODULE_NOT_FOUND';
    throw error;
  };
}

describe('Telemetry', () => {
  let sdks: ReturnType<typeof recordingSdks>;
  let telemetry: Telemetry | undefined;

  function start(options: Partial<TelemetryOptions> = {}): Telemetry {
    telemetry = new Telemetry({
      env: {},
      loadSentry: sdks.loadSentry,
      loadPostHog: sdks.loadPostHog,
      ...options,
    });
    telemetry.start();
    return telemetry;
  }

  beforeEach(() => {
    resetMockVscode();
    sdks = recordingSdks();
  });

  afterEach(async () => {
    await telemetry?.shutdown();
    telemetry = undefined;
  });

  describe('gates', () => {
    it('is off by default: nothing is loaded or constructed', () => {
      const t = start();

      expect(t.isActive).toBe(false);
      expect(sdks.loadSentry).not.toHaveBeenCalled();
      expect(sdks.loadPostHog).not.toHaveBeenCalled();
      expect(sdks.sentryClientOptions).toHaveLength(0);
      expect(sdks.posthogClients).toHaveLength(0);
    });

    it('constructs no client when vscode.env.isTelemetryEnabled is false', () => {
      allGatesOn();
      env.isTelemetryEnabled = false;

      const t = start();

      expect(t.isActive).toBe(false);
      expect(sdks.loadSentry).not.toHaveBeenCalled();
      expect(sdks.loadPostHog).not.toHaveBeenCalled();
      expect(sdks.sentryClientOptions).toHaveLength(0);
      expect(sdks.posthogClients).toHaveLength(0);
    });

    it('constructs no client when aragora.telemetry.enabled is false', () => {
      allGatesOn();
      setMockConfiguration({ 'aragora.telemetry.enabled': false });

      const t = start();

      expect(t.isActive).toBe(false);
      expect(sdks.loadSentry).not.toHaveBeenCalled();
      expect(sdks.loadPostHog).not.toHaveBeenCalled();
      expect(sdks.sentryClientOptions).toHaveLength(0);
      expect(sdks.posthogClients).toHaveLength(0);
    });

    it('constructs no client when both the DSN and the key are missing', () => {
      allGatesOn();
      setMockConfiguration({
        'aragora.telemetry.sentryDsn': '',
        'aragora.telemetry.posthogKey': '   ',
      });

      const t = start();

      expect(t.isActive).toBe(false);
      expect(sdks.loadSentry).not.toHaveBeenCalled();
      expect(sdks.loadPostHog).not.toHaveBeenCalled();
      expect(sdks.sentryClientOptions).toHaveLength(0);
      expect(sdks.posthogClients).toHaveLength(0);
    });

    it('constructs only Sentry when the PostHog key is missing', () => {
      allGatesOn();
      setMockConfiguration({ 'aragora.telemetry.posthogKey': '' });

      start();

      expect(sdks.sentryClientOptions).toHaveLength(1);
      expect(sdks.loadPostHog).not.toHaveBeenCalled();
      expect(sdks.posthogClients).toHaveLength(0);
    });

    it('constructs only PostHog when the Sentry DSN is missing', () => {
      allGatesOn();
      setMockConfiguration({ 'aragora.telemetry.sentryDsn': '' });

      start();

      expect(sdks.loadSentry).not.toHaveBeenCalled();
      expect(sdks.sentryClientOptions).toHaveLength(0);
      expect(sdks.posthogClients).toHaveLength(1);
    });

    it('reads the DSN and key from ARAGORA_SENTRY_DSN and ARAGORA_POSTHOG_KEY', () => {
      env.isTelemetryEnabled = true;
      setMockConfiguration({ 'aragora.telemetry.enabled': true });

      start({
        env: {
          ARAGORA_SENTRY_DSN: SENTRY_DSN,
          ARAGORA_POSTHOG_KEY: POSTHOG_KEY,
          ARAGORA_POSTHOG_HOST: 'http://127.0.0.1:3142',
        },
      });

      expect(sdks.sentryClientOptions[0]).toMatchObject({ dsn: SENTRY_DSN });
      expect(sdks.posthogClients[0]).toMatchObject({
        key: POSTHOG_KEY,
        options: { host: 'http://127.0.0.1:3142' },
      });
    });

    it('prefers the settings over the environment variables', () => {
      allGatesOn();

      start({
        env: {
          ARAGORA_SENTRY_DSN: 'https://other@o0.ingest.sentry.test/2',
          ARAGORA_POSTHOG_KEY: 'phc_other',
        },
      });

      expect(sdks.sentryClientOptions[0]).toMatchObject({ dsn: SENTRY_DSN });
      expect(sdks.posthogClients[0].key).toBe(POSTHOG_KEY);
    });

    it('ignores the environment variables while the setting is off', () => {
      env.isTelemetryEnabled = true;

      const t = start({
        env: { ARAGORA_SENTRY_DSN: SENTRY_DSN, ARAGORA_POSTHOG_KEY: POSTHOG_KEY },
      });

      expect(t.isActive).toBe(false);
      expect(sdks.loadSentry).not.toHaveBeenCalled();
      expect(sdks.loadPostHog).not.toHaveBeenCalled();
    });

    it('drops events once consent is revoked after start', async () => {
      allGatesOn();
      const t = start();

      env.isTelemetryEnabled = false;
      t.captureException(new Error('after revoke'));
      t.trackEvent('after_revoke');
      await t.shutdown();

      expect(sdks.sentryItems.filter((item) => item.type === 'event')).toHaveLength(0);
      expect(sdks.posthogBatches).toHaveLength(0);
    });
  });

  describe('when every gate passes', () => {
    it('sends errors to Sentry with release = package.json version and a non-empty environment', async () => {
      allGatesOn();
      const t = start({ extensionMode: ExtensionMode.Development });

      expect(t.isActive).toBe(true);
      expect(sdks.sentryClientOptions).toHaveLength(1);
      const options = sdks.sentryClientOptions[0];
      expect(options.dsn).toBe(SENTRY_DSN);
      expect(options.release).toBe(packageVersion);
      expect(options.environment).toBe('development');
      expect(options.sendDefaultPii).toBe(false);

      t.captureException(new Error('debate stream failed'));
      await t.shutdown();

      const events = sdks.sentryItems.filter((item) => item.type === 'event');
      expect(events).toHaveLength(1);
      const event = events[0].payload as {
        release?: string;
        environment?: string;
        exception?: { values?: Array<{ value?: string }> };
      };
      expect(event.release).toBe(packageVersion);
      expect(typeof event.environment).toBe('string');
      expect(event.environment).not.toHaveLength(0);
      expect(event.exception?.values?.[0]?.value).toBe('debate stream failed');
    });

    it('defaults the environment to production', () => {
      allGatesOn();

      start();

      expect(sdks.sentryClientOptions[0].environment).toBe('production');
    });

    it('redacts secrets from Sentry events before they are sent', async () => {
      allGatesOn();
      const t = start();

      t.captureException(new Error('request rejected for token=abc'));
      await t.shutdown();

      const serialized = JSON.stringify(sdks.sentryItems);
      expect(serialized).not.toContain('token=abc');
      expect(serialized).toContain('token=[REDACTED]');
    });

    it('sends events to PostHog with the release and environment', async () => {
      allGatesOn();
      const t = start({ extensionMode: ExtensionMode.Test });

      expect(sdks.posthogClients).toHaveLength(1);
      expect(sdks.posthogClients[0].key).toBe(POSTHOG_KEY);
      expect(sdks.posthogClients[0].options.host).toBe('https://us.i.posthog.com');

      t.trackEvent('debate_started', { rounds: 3 });
      await t.shutdown();

      const events = sdks.posthogBatches.flatMap((batch) => batch.batch);
      expect(events).toHaveLength(1);
      expect(events[0]).toMatchObject({
        event: 'debate_started',
        distinct_id: 'mock-machine-id',
        properties: { rounds: 3, release: packageVersion, environment: 'test' },
      });
      expect(sdks.posthogBatches[0].api_key).toBe(POSTHOG_KEY);
    });

    it('starts once even when start() is called again', () => {
      allGatesOn();
      const t = start();

      t.start();

      expect(sdks.sentryClientOptions).toHaveLength(1);
      expect(sdks.posthogClients).toHaveLength(1);
    });

    it('is inactive again after shutdown', async () => {
      allGatesOn();
      const t = start();

      await t.shutdown();
      t.captureException(new Error('late'));
      t.trackEvent('late');

      expect(t.isActive).toBe(false);
      expect(sdks.sentryItems.filter((item) => item.type === 'event')).toHaveLength(0);
      expect(sdks.posthogBatches).toHaveLength(0);
    });
  });

  describe('when the SDK modules are absent', () => {
    it('degrades to a no-op without throwing', async () => {
      allGatesOn();

      const t = start({
        loadSentry: missingModule('@sentry/node'),
        loadPostHog: missingModule('posthog-node'),
      });

      expect(t.isActive).toBe(false);
      expect(() => t.captureException(new Error('boom'))).not.toThrow();
      expect(() => t.trackEvent('noop')).not.toThrow();
      await expect(t.shutdown()).resolves.toBeUndefined();
    });

    it('keeps the SDK that did load', () => {
      allGatesOn();

      const t = start({ loadSentry: missingModule('@sentry/node') });

      expect(t.isActive).toBe(true);
      expect(sdks.posthogClients).toHaveLength(1);
    });

    it('survives an SDK whose constructor throws', () => {
      allGatesOn();
      const broken = () => ({
        NodeClient: class {
          constructor() {
            throw new Error('invalid DSN');
          }
        },
      });

      const t = start({ loadSentry: broken, loadPostHog: missingModule('posthog-node') });

      expect(t.isActive).toBe(false);
    });

    it('uses require() lazily and survives when the default loader cannot resolve the SDKs', async () => {
      let isolatedTelemetry: typeof import('../telemetry') | undefined;
      let isolatedVscode: typeof import('./vscode.mock') | undefined;
      jest.isolateModules(() => {
        jest.doMock('@sentry/node', missingModule('@sentry/node'));
        jest.doMock('posthog-node', missingModule('posthog-node'));
        /* eslint-disable @typescript-eslint/no-require-imports */
        isolatedTelemetry = require('../telemetry') as typeof import('../telemetry');
        isolatedVscode = require('./vscode.mock') as typeof import('./vscode.mock');
        /* eslint-enable @typescript-eslint/no-require-imports */
      });
      isolatedVscode!.setMockConfiguration({
        'aragora.telemetry.enabled': true,
        'aragora.telemetry.sentryDsn': SENTRY_DSN,
        'aragora.telemetry.posthogKey': POSTHOG_KEY,
      });

      try {
        const t = new isolatedTelemetry!.Telemetry({ env: {} });
        expect(() => t.start()).not.toThrow();
        expect(t.isActive).toBe(false);
        expect(() => t.captureException(new Error('boom'))).not.toThrow();
        await expect(t.shutdown()).resolves.toBeUndefined();

        // Both SDKs were really requested, and their absence was logged.
        const logged = isolatedVscode!.createdOutputChannels.map((c) => c.text).join('\n');
        expect(logged).toContain('@sentry/node is not available');
        expect(logged).toContain('posthog-node is not available');
      } finally {
        jest.dontMock('@sentry/node');
        jest.dontMock('posthog-node');
      }
    });
  });
});
