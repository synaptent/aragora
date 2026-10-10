import pino from 'pino';

const LOG_LEVELS = ['trace', 'debug', 'info', 'warn', 'error', 'fatal', 'silent'] as const;
type LogLevel = (typeof LOG_LEVELS)[number];

function isLogLevel(value: string): value is LogLevel {
  return (LOG_LEVELS as readonly string[]).includes(value);
}

// pino throws at construction on unknown level names, so a typo must not crash the server.
const requestedLevel = process.env.LOG_LEVEL || '';
const rejectedLevel = requestedLevel && !isLogLevel(requestedLevel) ? requestedLevel : undefined;

// Node route handlers only, never import this module from client or edge code.
export const logger = pino({
  level: isLogLevel(requestedLevel) ? requestedLevel : 'info',
  redact: {
    paths: ['authorization', 'cookie', '*.password', '*.token', '*.apiKey'],
    censor: '[REDACTED]',
  },
});

if (rejectedLevel !== undefined) {
  logger.warn(
    { rejectedLogLevel: rejectedLevel },
    `Ignoring invalid LOG_LEVEL ${JSON.stringify(rejectedLevel)}; using "info" (accepted: ${LOG_LEVELS.join(', ')})`,
  );
}
