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

  it.each(['trace', 'debug', 'info', 'warn', 'error', 'fatal', 'silent'])(
    'accepts LOG_LEVEL=%s without a warning',
    (value) => {
      process.env.LOG_LEVEL = value;
      const { logger } = require('../logger');
      expect(logger.level).toBe(value);
      expect(output).toHaveLength(0);
    },
  );

  it.each([undefined, ''])('emits no level warning when LOG_LEVEL is %p', (value) => {
    if (value !== undefined) process.env.LOG_LEVEL = value;
    require('../logger');
    expect(output).toHaveLength(0);
  });

  it.each(['verbose', 'warning', 'INFO', ' info'])(
    'falls back to info and warns once when LOG_LEVEL=%p',
    (value) => {
      process.env.LOG_LEVEL = value;
      let logger: { level: string; debug: (msg: string) => void } | undefined;
      expect(() => {
        logger = require('../logger').logger;
      }).not.toThrow();
      expect(logger?.level).toBe('info');
      expect(output).toHaveLength(1);
      expect(JSON.parse(output[0])).toMatchObject({
        level: 40,
        rejectedLogLevel: value,
        msg: expect.stringContaining(JSON.stringify(value)),
      });
      logger?.debug('hidden');
      expect(output).toHaveLength(1);
    },
  );

  it('warns once per module initialization', () => {
    process.env.LOG_LEVEL = 'verbose';
    require('../logger');
    require('../logger');
    expect(output).toHaveLength(1);
    jest.resetModules();
    require('../logger');
    expect(output).toHaveLength(2);
  });

  it('keeps child bindings and redaction on child loggers', () => {
    const { logger } = require('../logger');
    logger.child({ route: '/healthz/' }).info({ authorization: 'Bearer y' }, 'child');
    expect(JSON.parse(output.join(''))).toMatchObject({
      level: 30,
      route: '/healthz/',
      authorization: '[REDACTED]',
      msg: 'child',
    });
  });
});
