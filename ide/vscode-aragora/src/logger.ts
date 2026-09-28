/**
 * Extension logger: writes to the "Aragora" OutputChannel, filtered by the
 * `aragora.logLevel` setting, with secrets redacted before anything is written.
 */

import * as vscode from 'vscode';

export const OUTPUT_CHANNEL_NAME = 'Aragora';
export const REDACTED = '[REDACTED]';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';
type LogLevelSetting = LogLevel | 'off';

const LEVEL_RANK: Record<LogLevelSetting, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  off: 100,
};

const DEFAULT_LEVEL: LogLevelSetting = 'info';

const SECRET_KEY = /(api[_-]?key|token|secret|password|authorization)/i;

// A key such as `apiKey`, `x-api-key`, `access_token` or `Authorization`, not starting mid-word.
const KEY = String.raw`(?<![\w-])[\w-]*?(?:api[_-]?key|token|secret|password|authorization)[\w-]*`;
const SEPARATOR = String.raw`\s*[:=]\s*`;

const REDACTION_RULES: Array<[RegExp, string]> = [
  // Quoted values, optionally with a quoted key: apiKey: "k", {"access_token":"v"}, 'secret'='v'.
  [
    new RegExp(String.raw`(["']?)(${KEY})\1(${SEPARATOR})(["'])(?:\\.|(?!\4).)*\4`, 'gi'),
    `$1$2$1$3$4${REDACTED}$4`,
  ],
  // Unquoted values, including an auth scheme: token=abc, Authorization: Bearer x.
  // Skips values already redacted, also when JSON-escaped (apiKey: \"[REDACTED]\").
  [
    new RegExp(
      String.raw`(${KEY})(${SEPARATOR})(?!\\?["']?\[REDACTED\])(?:(?:Bearer|Basic|Token|Digest)\s+)?[^\s"',;&}\]]+`,
      'gi',
    ),
    `$1$2${REDACTED}`,
  ],
  // Bearer credentials that appear without a key.
  [/\bBearer\s+[A-Za-z0-9._~+/=-]+/g, `Bearer ${REDACTED}`],
];

/** Replaces secret values in `text` with {@link REDACTED}. */
export function redact(text: string): string {
  return REDACTION_RULES.reduce((result, [pattern, replacement]) => {
    return result.replace(pattern, replacement);
  }, text);
}

function serialize(value: object): string {
  const ancestors: unknown[] = [];
  return JSON.stringify(value, function (this: unknown, key: string, item: unknown) {
    if (key && SECRET_KEY.test(key) && item !== null && item !== undefined && item !== '') {
      return REDACTED;
    }
    // Redact before JSON escaping: in the escaped text a backslash precedes each
    // quote, so the quoted-value rule no longer matches. This also covers the
    // message of a nested Error, which is walked as the object returned below.
    if (typeof item === 'string') return redact(item);
    if (item instanceof Error) {
      return { name: item.name, message: item.message };
    }
    if (typeof item !== 'object' || item === null) {
      return item;
    }
    // JSON.stringify calls the replacer with `this` bound to the parent object.
    while (ancestors.length > 0 && ancestors[ancestors.length - 1] !== this) {
      ancestors.pop();
    }
    if (ancestors.includes(item)) {
      return '[Circular]';
    }
    ancestors.push(item);
    return item;
  });
}

function format(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value instanceof Error) return value.stack ?? `${value.name}: ${value.message}`;
  if (typeof value === 'object' && value !== null) {
    try {
      return serialize(value);
    } catch {
      return Object.prototype.toString.call(value);
    }
  }
  return String(value);
}

type ErrorReporter = (error: Error) => void;

export class Logger {
  private channel: vscode.OutputChannel | undefined;
  private errorReporter: ErrorReporter | undefined;

  debug(message: string, ...args: unknown[]): void {
    this.write('debug', message, args);
  }

  info(message: string, ...args: unknown[]): void {
    this.write('info', message, args);
  }

  warn(message: string, ...args: unknown[]): void {
    this.write('warn', message, args);
  }

  error(message: string, ...args: unknown[]): void {
    this.write('error', message, args);
    this.report(args);
  }

  /** Receives the first `Error` passed to each `error()` call, e.g. to send it to telemetry. */
  setErrorReporter(reporter: ErrorReporter | undefined): void {
    this.errorReporter = reporter;
  }

  dispose(): void {
    this.channel?.dispose();
    this.channel = undefined;
  }

  private write(level: LogLevel, message: string, args: unknown[]): void {
    // Logging must never break the caller, even without a usable vscode API (e.g. in tests).
    try {
      if (LEVEL_RANK[level] < LEVEL_RANK[this.threshold()]) return;
      const text = [message, ...args.map(format)].join(' ');
      this.getChannel().appendLine(`${new Date().toISOString()} [${level}] ${redact(text)}`);
    } catch {
      // Nowhere left to report a logging failure.
    }
  }

  private report(args: unknown[]): void {
    const error = args.find((arg): arg is Error => arg instanceof Error);
    if (!error || !this.errorReporter) return;
    try {
      this.errorReporter(error);
    } catch {
      // A failing reporter must not break logging.
    }
  }

  private threshold(): LogLevelSetting {
    const configured = vscode.workspace
      .getConfiguration('aragora')
      .get<string>('logLevel', DEFAULT_LEVEL);
    return Object.hasOwn(LEVEL_RANK, configured) ? (configured as LogLevelSetting) : DEFAULT_LEVEL;
  }

  private getChannel(): vscode.OutputChannel {
    this.channel ??= vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);
    return this.channel;
  }
}

let sharedLogger: Logger | undefined;

/** The logger shared by the whole extension. */
export function getLogger(): Logger {
  sharedLogger ??= new Logger();
  return sharedLogger;
}
