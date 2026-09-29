/**
 * Frontend crash telemetry reporter.
 *
 * Captures React runtime errors, deduplicates by fingerprint, rate-limits
 * submissions, and batches them to the backend observability endpoint.
 */

import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CrashReport {
  /** Unique fingerprint derived from message + stack */
  fingerprint: string;
  /** Error message */
  message: string;
  /** Component stack trace (React-provided) */
  componentStack: string | null;
  /** JS stack trace */
  stack: string | null;
  /** Page URL where the crash occurred */
  url: string;
  /** ISO-8601 timestamp */
  timestamp: string;
  /** Browser user agent string */
  userAgent: string;
  /** Session identifier for correlating crashes */
  sessionId: string;
  /** Component name if available */
  componentName: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SESSION_STORAGE_KEY = 'aragora_crash_reports';
const MAX_STORED_CRASHES = 50;
const MAX_REPORTS_PER_MINUTE = 10;
const BATCH_INTERVAL_MS = 5_000;
const CRASH_ENDPOINT = '/api/v1/observability/crashes';

/** Simple FNV-1a-inspired string hash to produce a fingerprint. */
function hashFingerprint(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = (hash * 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

/** Generate or retrieve a per-tab session ID. */
function getSessionId(): string {
  if (typeof sessionStorage === 'undefined') return 'unknown';
  let id = sessionStorage.getItem('aragora_session_id');
  if (!id) {
    id = `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    sessionStorage.setItem('aragora_session_id', id);
  }
  return id;
}

// ---------------------------------------------------------------------------
// CrashReporter
// ---------------------------------------------------------------------------

export class CrashReporter {
  private queue: CrashReport[] = [];
  private seenFingerprints = new Set<string>();
  private reportTimestamps: number[] = [];
  private batchTimer: ReturnType<typeof setInterval> | null = null;
  private sessionId: string;

  constructor() {
    this.sessionId = getSessionId();
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  /** Start the batch flush timer. */
  start(): void {
    if (this.batchTimer) return;
    this.batchTimer = setInterval(() => this.flush(), BATCH_INTERVAL_MS);
  }

  /** Stop the batch flush timer. */
  stop(): void {
    if (this.batchTimer) {
      clearInterval(this.batchTimer);
      this.batchTimer = null;
    }
  }

  /**
   * Capture a crash from a React error boundary or global handler.
   *
   * Returns `true` if the report was accepted (not deduplicated / rate-limited).
   */
  capture(
    error: Error,
    options?: { componentStack?: string | null; componentName?: string | null },
  ): boolean {
    const message = error.message || String(error);
    const stack = error.stack ?? null;
    const componentStack = options?.componentStack ?? null;

    // Build fingerprint from message + first meaningful stack frame
    const fingerSource = `${message}::${(stack ?? '').split('\n').slice(0, 3).join('')}`;
    const fingerprint = hashFingerprint(fingerSource);

    // Deduplicate
    if (this.seenFingerprints.has(fingerprint)) {
      return false;
    }

    // Rate limit
    const now = Date.now();
    this.reportTimestamps = this.reportTimestamps.filter((t) => now - t < 60_000);
    if (this.reportTimestamps.length >= MAX_REPORTS_PER_MINUTE) {
      return false;
    }

    this.seenFingerprints.add(fingerprint);
    this.reportTimestamps.push(now);

    const report: CrashReport = {
      fingerprint,
      message,
      componentStack,
      stack,
      url: typeof window !== 'undefined' ? window.location.href : '',
      timestamp: new Date().toISOString(),
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
      sessionId: this.sessionId,
      componentName: options?.componentName ?? null,
    };

    this.queue.push(report);
    this.persistToSession(report);

    return true;
  }

  /** Flush the current batch to the backend. */
  async flush(): Promise<void> {
    if (this.queue.length === 0) return;

    const batch = this.queue.splice(0);

    try {
      const url = `${API_BASE_URL}${CRASH_ENDPOINT}`;
      await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reports: batch }),
        // Fire-and-forget; don't block the UI
        keepalive: true,
      });
    } catch {
      // Network failure -- re-queue for next attempt (drop if too many)
      if (this.queue.length < 100) {
        this.queue.push(...batch);
      }
    }
  }

  /** Return crashes stored in sessionStorage for debugging. */
  getStoredCrashes(): CrashReport[] {
    if (typeof sessionStorage === 'undefined') return [];
    try {
      const raw = sessionStorage.getItem(SESSION_STORAGE_KEY);
      return raw ? (JSON.parse(raw) as CrashReport[]) : [];
    } catch {
      return [];
    }
  }

  /** Clear the deduplication set (useful after navigation). */
  resetDeduplication(): void {
    this.seenFingerprints.clear();
  }

  // -----------------------------------------------------------------------
  // Internals
  // -----------------------------------------------------------------------

  private persistToSession(report: CrashReport): void {
    if (typeof sessionStorage === 'undefined') return;
    try {
      const existing = this.getStoredCrashes();
      existing.push(report);
      // Keep bounded
      const trimmed = existing.slice(-MAX_STORED_CRASHES);
      sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(trimmed));
    } catch {
      // sessionStorage might be full -- ignore
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

let _instance: CrashReporter | null = null;

export function getCrashReporter(): CrashReporter {
  if (!_instance) {
    _instance = new CrashReporter();
    _instance.start();
  }
  return _instance;
}
