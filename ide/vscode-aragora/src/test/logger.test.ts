/**
 * Tests for the OutputChannel logger (src/logger.ts).
 */

import {
  createdOutputChannels,
  resetMockVscode,
  setMockConfiguration,
  window,
  type MockOutputChannel,
} from './vscode.mock';
import { Logger, OUTPUT_CHANNEL_NAME, REDACTED, getLogger, redact } from '../logger';

function onlyChannel(): MockOutputChannel {
  expect(createdOutputChannels).toHaveLength(1);
  return createdOutputChannels[0];
}

describe('Logger', () => {
  let logger: Logger;

  beforeEach(() => {
    resetMockVscode();
    logger = new Logger();
  });

  afterEach(() => {
    logger.dispose();
    jest.restoreAllMocks();
  });

  describe('output channel', () => {
    it('appends to an OutputChannel named Aragora', () => {
      const create = jest.spyOn(window, 'createOutputChannel');

      logger.info('extension activated');

      expect(OUTPUT_CHANNEL_NAME).toBe('Aragora');
      expect(create).toHaveBeenCalledTimes(1);
      expect(create).toHaveBeenCalledWith('Aragora');
      const channel = onlyChannel();
      expect(channel.name).toBe('Aragora');
      expect(channel.lines).toHaveLength(1);
      expect(channel.lines[0]).toMatch(/\[info\] extension activated$/);
    });

    it('creates the channel lazily and only once', () => {
      expect(createdOutputChannels).toHaveLength(0);

      logger.info('one');
      logger.warn('two');
      logger.error('three');

      expect(onlyChannel().lines).toHaveLength(3);
    });

    it('disposes the channel and recreates it on the next write', () => {
      logger.info('before');
      const first = onlyChannel();

      logger.dispose();
      expect(first.disposed).toBe(true);

      logger.info('after');
      expect(createdOutputChannels).toHaveLength(2);
      expect(createdOutputChannels[1].name).toBe('Aragora');
    });

    it('getLogger returns one shared logger', () => {
      expect(getLogger()).toBe(getLogger());
    });
  });

  describe('redaction', () => {
    it('redacts token=abc, Authorization: Bearer x and apiKey: "k"', () => {
      logger.info('token=abc');
      logger.info('Authorization: Bearer x');
      logger.info('apiKey: "k"');

      const text = onlyChannel().text;

      // Whole key=value fragments are gone...
      expect(text).not.toContain('token=abc');
      expect(text).not.toContain('Authorization: Bearer x');
      expect(text).not.toContain('Bearer x');
      expect(text).not.toContain('apiKey: "k"');
      expect(text).not.toContain('"k"');
      // ...no raw secret value survives as a token of its own anywhere in the text...
      expect(text).not.toMatch(/\babc\b/);
      expect(text).not.toMatch(/\bx\b/);
      expect(text).not.toMatch(/\bk\b/);
      // ...and each key now carries the fixed redaction token.
      expect(text).toContain(`token=${REDACTED}`);
      expect(text).toContain(`Authorization: ${REDACTED}`);
      expect(text).toContain(`apiKey: "${REDACTED}"`);
    });

    it('redacts the contract inputs when they share one message', () => {
      logger.warn('retrying with token=abc and Authorization: Bearer x and apiKey: "k"');

      const line = onlyChannel().lines[0];
      expect(line).toContain(
        `retrying with token=${REDACTED} and Authorization: ${REDACTED} and apiKey: "${REDACTED}"`,
      );
    });

    it.each([
      ['api_key=s3cr3t', `api_key=${REDACTED}`],
      ['API-KEY: s3cr3t', `API-KEY: ${REDACTED}`],
      ['x-api-key: s3cr3t', `x-api-key: ${REDACTED}`],
      ['client_secret=s3cr3t&grant=1', `client_secret=${REDACTED}&grant=1`],
      ['PASSWORD = s3cr3t', `PASSWORD = ${REDACTED}`],
      ['{"access_token":"s3cr3t"}', `{"access_token":"${REDACTED}"}`],
      ["refreshToken: 's3cr3t'", `refreshToken: '${REDACTED}'`],
      ['authorization=Basic czNjcjN0', `authorization=${REDACTED}`],
      ['sent Bearer s3cr3t.value to the API', `sent Bearer ${REDACTED} to the API`],
    ])('redacts %s', (input, expected) => {
      expect(redact(input)).toBe(expected);
      expect(redact(input)).not.toContain('s3cr3t');
    });

    it('leaves text without secrets unchanged', () => {
      const text = 'Found 3 security issues in 2 files; the token was refreshed';
      expect(redact(text)).toBe(text);
    });

    it('redacts secret keys inside structured arguments', () => {
      logger.error('request failed', {
        url: '/api/debates',
        headers: { Authorization: 'Bearer x', 'Content-Type': 'application/json' },
        apiKey: 'k',
        nested: { password: 'hunter2', note: 'token=abc' },
      });

      const line = onlyChannel().lines[0];
      expect(line).toContain('/api/debates');
      expect(line).toContain('application/json');
      expect(line).not.toContain('Bearer x');
      expect(line).not.toContain('"k"');
      expect(line).not.toContain('hunter2');
      expect(line).not.toContain('token=abc');
      expect(line).toContain(`"Authorization":"${REDACTED}"`);
      expect(line).toContain(`"apiKey":"${REDACTED}"`);
    });

    it('redacts secrets inside Error messages', () => {
      logger.error('Failed to connect:', new Error('handshake rejected for token=abc'));

      const line = onlyChannel().lines[0];
      expect(line).toContain('Failed to connect:');
      expect(line).toContain(`token=${REDACTED}`);
      expect(line).not.toContain('token=abc');
    });

    describe('double-quoted secrets inside structured arguments', () => {
      // The appended line without its leading ISO timestamp.
      function onlyLineBody(): string {
        const line = onlyChannel().lines[0];
        expect(line).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z /);
        return line.replace(/^\S+ /, '');
      }

      it('redacts apiKey: "k" in a string field', () => {
        logger.info('x', { detail: 'apiKey: "k"' });

        const body = onlyLineBody();
        expect(body).not.toContain('"k"');
        expect(body).not.toContain('k\\"');
        expect(body).not.toContain(`${REDACTED}"${REDACTED}`);
        expect(body).toBe(`[info] x {"detail":"apiKey: \\"${REDACTED}\\""}`);
      });

      it('redacts password: "hunter2" in a string field', () => {
        logger.info('x', { note: 'password: "hunter2"' });

        const body = onlyLineBody();
        expect(body).not.toContain('hunter2');
        expect(body).not.toContain(`${REDACTED}"${REDACTED}`);
        expect(body).toBe(`[info] x {"note":"password: \\"${REDACTED}\\""}`);
      });

      it('redacts token="abc" in a nested Error message', () => {
        logger.info('x', { cause: new Error('token="abc"') });

        const body = onlyLineBody();
        expect(body).not.toMatch(/\babc\b/);
        expect(body).not.toContain(`${REDACTED}"${REDACTED}`);
        expect(body).toBe(
          `[info] x {"cause":{"name":"Error","message":"token=\\"${REDACTED}\\""}}`,
        );
      });
    });

    it('formats primitives and circular objects without throwing', () => {
      const circular: Record<string, unknown> = { name: 'loop' };
      circular.self = circular;

      logger.info('values', 42, true, undefined, null, circular);

      const line = onlyChannel().lines[0];
      expect(line).toContain('values 42 true undefined null');
      expect(line).toContain('[Circular]');
    });
  });

  describe('levels from aragora.logLevel', () => {
    function levelsWritten(): string[] {
      logger.debug('d');
      logger.info('i');
      logger.warn('w');
      logger.error('e');
      const channel = createdOutputChannels[0];
      return channel ? channel.lines.map((line) => /\[(\w+)\]/.exec(line)?.[1] ?? '') : [];
    }

    it('defaults to info', () => {
      expect(levelsWritten()).toEqual(['info', 'warn', 'error']);
    });

    it('writes debug when set to debug', () => {
      setMockConfiguration({ 'aragora.logLevel': 'debug' });
      expect(levelsWritten()).toEqual(['debug', 'info', 'warn', 'error']);
    });

    it('writes only warn and error when set to warn', () => {
      setMockConfiguration({ 'aragora.logLevel': 'warn' });
      expect(levelsWritten()).toEqual(['warn', 'error']);
    });

    it('writes only error when set to error', () => {
      setMockConfiguration({ 'aragora.logLevel': 'error' });
      expect(levelsWritten()).toEqual(['error']);
    });

    it('writes nothing and creates no channel when set to off', () => {
      setMockConfiguration({ 'aragora.logLevel': 'off' });
      expect(levelsWritten()).toEqual([]);
      expect(createdOutputChannels).toHaveLength(0);
    });

    it('falls back to info for an unknown level', () => {
      setMockConfiguration({ 'aragora.logLevel': 'verbose' });
      expect(levelsWritten()).toEqual(['info', 'warn', 'error']);
    });

    it('re-reads the setting on every call', () => {
      logger.debug('hidden');
      setMockConfiguration({ 'aragora.logLevel': 'debug' });
      logger.debug('shown');

      expect(onlyChannel().lines).toHaveLength(1);
      expect(onlyChannel().lines[0]).toContain('[debug] shown');
    });
  });

  describe('error reporter', () => {
    it('forwards the first Error argument of error() calls', () => {
      const reporter = jest.fn();
      const failure = new Error('boom');
      logger.setErrorReporter(reporter);

      logger.error('Handler error:', failure);
      logger.error('no error object here');
      logger.warn('warnings are not reported', new Error('ignored'));

      expect(reporter).toHaveBeenCalledTimes(1);
      expect(reporter).toHaveBeenCalledWith(failure);
    });

    it('keeps logging when the reporter throws', () => {
      logger.setErrorReporter(() => {
        throw new Error('reporter down');
      });

      expect(() => logger.error('still logged', new Error('boom'))).not.toThrow();
      expect(onlyChannel().lines[0]).toContain('still logged');
    });

    it('stops forwarding after the reporter is cleared', () => {
      const reporter = jest.fn();
      logger.setErrorReporter(reporter);
      logger.setErrorReporter(undefined);

      logger.error('Handler error:', new Error('boom'));

      expect(reporter).not.toHaveBeenCalled();
    });
  });
});
