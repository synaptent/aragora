/** @jest-environment node */

describe('server logger', () => {
  const originalLevel = process.env.LOG_LEVEL;
  let output: string[];

  beforeEach(() => {
    jest.resetModules();
    delete process.env.LOG_LEVEL;
    output = [];
    jest.spyOn(process.stdout, 'write').mockImplementation((chunk) => {
      output.push(String(chunk));
      return true;
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
    if (originalLevel === undefined) delete process.env.LOG_LEVEL;
    else process.env.LOG_LEVEL = originalLevel;
  });

  it('redacts credentials without mutating the input or hiding safe fields', () => {
    const { logger } = require('../logger');
    const input = {
      authorization: 'Bearer x',
      cookie: 'session=private',
      user: { password: 'p', token: 'private-token', apiKey: 'private-key', name: 'test' },
    };
    logger.info(input, 'm');
    const record = JSON.parse(output.join(''));

    expect(record).toMatchObject({
      level: 30,
      msg: 'm',
      authorization: '[REDACTED]',
      cookie: '[REDACTED]',
      user: { password: '[REDACTED]', token: '[REDACTED]', apiKey: '[REDACTED]', name: 'test' },
    });
    for (const secret of ['Bearer x', 'session=private', '"p"', 'private-token', 'private-key']) {
      expect(output.join('')).not.toContain(secret);
    }
    expect(input.authorization).toBe('Bearer x');
    expect(input.user.password).toBe('p');
  });

  it.each([undefined, ''])('defaults to info and suppresses debug for %s', (value) => {
    if (value !== undefined) process.env.LOG_LEVEL = value;
    const { logger } = require('../logger');
    expect(logger.level).toBe('info');
    logger.debug('hidden');
    logger.info({ req: { url: '/healthz/' } }, 'request');
    expect(output).toHaveLength(1);
    expect(JSON.parse(output[0])).toMatchObject({
      level: 30,
      msg: 'request',
      req: { url: '/healthz/' },
    });
  });

  it('emits debug records when LOG_LEVEL=debug', () => {
    process.env.LOG_LEVEL = 'debug';
    const { logger } = require('../logger');
    expect(logger.level).toBe('debug');
    logger.debug('visible');
    expect(JSON.parse(output.join(''))).toMatchObject({ level: 20, msg: 'visible' });
  });
});
