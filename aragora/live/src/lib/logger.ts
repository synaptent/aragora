import pino from 'pino';

// Node route handlers only, never import this module from client or edge code.
export const logger = pino({
  level: process.env.LOG_LEVEL || 'info',
  redact: {
    paths: ['authorization', 'cookie', '*.password', '*.token', '*.apiKey'],
    censor: '[REDACTED]',
  },
});
