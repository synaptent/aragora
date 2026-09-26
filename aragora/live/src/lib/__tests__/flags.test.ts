/** @jest-environment node */

describe('build-time flags', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_FLAG_DISABLE_STREAMING;
    delete process.env.NEXT_PUBLIC_FLAG_DISABLE_AUDIENCE;
    delete process.env.NEXT_PUBLIC_ENABLE_STREAMING;
    delete process.env.NEXT_PUBLIC_ENABLE_AUDIENCE;
  });

  afterEach(() => {
    process.env = originalEnv;
  });

  it('defaults both opt-out flags to false and preserves existing enabled features', () => {
    const { flags } = require('../flags');
    expect(flags).toEqual({ disableStreaming: false, disableAudience: false });
    const config = require('../../config');
    expect(config.ENABLE_STREAMING).toBe(true);
    expect(config.ENABLE_AUDIENCE).toBe(true);
  });

  it.each(['', 'false', '1', 'TRUE'])('does not enable flags for %s', (value) => {
    process.env.NEXT_PUBLIC_FLAG_DISABLE_STREAMING = value;
    process.env.NEXT_PUBLIC_FLAG_DISABLE_AUDIENCE = value;
    expect(require('../flags').flags).toEqual({ disableStreaming: false, disableAudience: false });
  });

  it.each(['STREAMING', 'AUDIENCE'])('disables only the selected %s feature', (feature) => {
    process.env[`NEXT_PUBLIC_FLAG_DISABLE_${feature}`] = 'true';
    const config = require('../../config');
    expect(config.ENABLE_STREAMING).toBe(feature !== 'STREAMING');
    expect(config.ENABLE_AUDIENCE).toBe(feature !== 'AUDIENCE');
  });

  it('keeps legacy explicit false values effective', () => {
    process.env.NEXT_PUBLIC_ENABLE_STREAMING = 'false';
    process.env.NEXT_PUBLIC_ENABLE_AUDIENCE = 'false';
    const config = require('../../config');
    expect(config.ENABLE_STREAMING).toBe(false);
    expect(config.ENABLE_AUDIENCE).toBe(false);
  });
});
