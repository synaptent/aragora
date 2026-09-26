/**
 * Opt-in error reporting (Sentry) and product analytics (PostHog).
 *
 * Clients are created only when all three gates pass: VS Code telemetry is
 * enabled, `aragora.telemetry.enabled` is true, and a Sentry DSN or PostHog key
 * is configured. The SDKs are optional at runtime (the VSIX ships without
 * node_modules), so they are loaded lazily and their absence turns telemetry
 * into a no-op.
 */

import * as vscode from 'vscode';
import { getLogger, redact } from './logger';

const DEFAULT_POSTHOG_HOST = 'https://us.i.posthog.com';
const SHUTDOWN_TIMEOUT_MS = 2_000;

interface SentryClientLike {
  init(): void;
  close(timeoutMs?: number): PromiseLike<boolean>;
}

interface SentryScopeLike {
  setClient(client: SentryClientLike): void;
  captureException(exception: unknown): string;
}

interface SentrySdk {
  NodeClient: new (options: Record<string, unknown>) => SentryClientLike;
  Scope: new () => SentryScopeLike;
  defaultStackParser: unknown;
  makeNodeTransport: unknown;
}

interface SentryEventLike {
  message?: string;
  exception?: { values?: Array<{ value?: string }> };
}

interface PostHogClientLike {
  capture(message: {
    distinctId: string;
    event: string;
    properties?: Record<string, unknown>;
  }): void;
  shutdown(timeoutMs?: number): Promise<void>;
}

interface PostHogSdk {
  PostHog: new (apiKey: string, options: Record<string, unknown>) => PostHogClientLike;
}

export interface TelemetryOptions {
  /** A `vscode.ExtensionMode` value; selects the reported environment. */
  extensionMode?: number;
  /** Source of `ARAGORA_SENTRY_DSN`, `ARAGORA_POSTHOG_KEY` and `ARAGORA_POSTHOG_HOST`. */
  env?: Record<string, string | undefined>;
  loadSentry?: () => unknown;
  loadPostHog?: () => unknown;
}

// Literal require() calls, kept inside functions so nothing loads until every gate has passed.
/* eslint-disable @typescript-eslint/no-require-imports */
const requireSentry = (): unknown => require('@sentry/node');
const requirePostHog = (): unknown => require('posthog-node');

function readPackageVersion(): string {
  try {
    return (require('../package.json') as { version?: string }).version ?? 'unknown';
  } catch {
    return 'unknown';
  }
}
/* eslint-enable @typescript-eslint/no-require-imports */

function environmentFor(extensionMode: number | undefined): string {
  if (extensionMode === vscode.ExtensionMode.Development) return 'development';
  if (extensionMode === vscode.ExtensionMode.Test) return 'test';
  return 'production';
}

function nonEmpty(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function isModuleNotFound(error: unknown): boolean {
  return (error as NodeJS.ErrnoException | undefined)?.code === 'MODULE_NOT_FOUND';
}

function scrubEvent<E extends SentryEventLike>(event: E): E {
  if (event.message) event.message = redact(event.message);
  for (const exception of event.exception?.values ?? []) {
    if (exception.value) exception.value = redact(exception.value);
  }
  return event;
}

function consentGiven(): boolean {
  try {
    return (
      vscode.env.isTelemetryEnabled &&
      vscode.workspace.getConfiguration('aragora').get<boolean>('telemetry.enabled', false) === true
    );
  } catch {
    return false;
  }
}

export class Telemetry {
  readonly release = readPackageVersion();
  readonly environment: string;
  private readonly env: Record<string, string | undefined>;
  private readonly loadSentry: () => unknown;
  private readonly loadPostHog: () => unknown;
  private started = false;
  private sentry: { client: SentryClientLike; scope: SentryScopeLike } | undefined;
  private posthog: PostHogClientLike | undefined;

  constructor(options: TelemetryOptions = {}) {
    this.environment = environmentFor(options.extensionMode);
    this.env = options.env ?? process.env;
    this.loadSentry = options.loadSentry ?? requireSentry;
    this.loadPostHog = options.loadPostHog ?? requirePostHog;
  }

  get isActive(): boolean {
    return this.sentry !== undefined || this.posthog !== undefined;
  }

  /** Creates the clients whose gates pass. Never throws; later calls do nothing. */
  start(): void {
    if (this.started) return;
    this.started = true;
    if (!consentGiven()) return;

    const config = vscode.workspace.getConfiguration('aragora');
    const sentryDsn =
      nonEmpty(config.get<string>('telemetry.sentryDsn')) ?? nonEmpty(this.env.ARAGORA_SENTRY_DSN);
    const posthogKey =
      nonEmpty(config.get<string>('telemetry.posthogKey')) ??
      nonEmpty(this.env.ARAGORA_POSTHOG_KEY);

    if (sentryDsn) this.sentry = this.startSentry(sentryDsn);
    if (posthogKey) this.posthog = this.startPostHog(posthogKey);
    if (this.isActive) {
      getLogger().info(`Telemetry enabled (${this.environment}, release ${this.release}).`);
    }
  }

  captureException(error: unknown): void {
    if (!this.sentry || !consentGiven()) return;
    try {
      this.sentry.scope.captureException(error);
    } catch {
      // Error reporting must never surface errors of its own.
    }
  }

  trackEvent(event: string, properties: Record<string, unknown> = {}): void {
    if (!this.posthog || !consentGiven()) return;
    try {
      this.posthog.capture({
        distinctId: vscode.env.machineId,
        event,
        properties: { ...properties, release: this.release, environment: this.environment },
      });
    } catch {
      // Analytics must never surface errors of its own.
    }
  }

  /** Flushes queued events and releases both clients. */
  async shutdown(): Promise<void> {
    const { sentry, posthog } = this;
    this.sentry = undefined;
    this.posthog = undefined;
    await Promise.allSettled([
      sentry?.client.close(SHUTDOWN_TIMEOUT_MS),
      posthog?.shutdown(SHUTDOWN_TIMEOUT_MS),
    ]);
  }

  private startSentry(dsn: string): Telemetry['sentry'] {
    try {
      const sdk = this.loadSentry() as SentrySdk;
      // A private client and scope rather than Sentry.init(): the extension host is
      // shared with other extensions, so no global handlers or integrations.
      const client = new sdk.NodeClient({
        dsn,
        release: this.release,
        environment: this.environment,
        transport: sdk.makeNodeTransport,
        stackParser: sdk.defaultStackParser,
        integrations: [],
        sendDefaultPii: false,
        includeServerName: false,
        beforeSend: scrubEvent,
      });
      const scope = new sdk.Scope();
      scope.setClient(client);
      client.init();
      return { client, scope };
    } catch (error) {
      this.reportLoadFailure('@sentry/node', error);
      return undefined;
    }
  }

  private startPostHog(apiKey: string): PostHogClientLike | undefined {
    try {
      const sdk = this.loadPostHog() as PostHogSdk;
      return new sdk.PostHog(apiKey, {
        host: nonEmpty(this.env.ARAGORA_POSTHOG_HOST) ?? DEFAULT_POSTHOG_HOST,
        flushAt: 20,
        flushInterval: 10_000,
        disableGeoip: true,
      });
    } catch (error) {
      this.reportLoadFailure('posthog-node', error);
      return undefined;
    }
  }

  private reportLoadFailure(sdkName: string, error: unknown): void {
    if (isModuleNotFound(error)) {
      getLogger().info(`Telemetry: ${sdkName} is not available; it stays off.`);
    } else {
      getLogger().warn(`Telemetry: could not start ${sdkName}:`, error);
    }
  }
}
