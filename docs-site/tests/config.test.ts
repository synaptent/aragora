import { createRequire } from 'node:module';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const CONFIG_PATH = path.resolve(__dirname, '..', 'docusaurus.config.js');

type SiteConfig = {
  url: string;
  baseUrl: string;
  onBrokenLinks: string;
  markdown?: { hooks?: { onBrokenMarkdownLinks?: string } };
  plugins?: unknown[];
};

function loadConfig(): SiteConfig {
  // The config module reads process.env at require time; drop the cached copy
  // so each test observes the environment it set up.
  delete require.cache[CONFIG_PATH];
  return require(CONFIG_PATH);
}

describe('docusaurus.config.js', () => {
  it('defines a valid production url and baseUrl', () => {
    const config = loadConfig();
    expect(() => new URL(config.url)).not.toThrow();
    expect(new URL(config.url).protocol).toBe('https:');
    expect(config.baseUrl.startsWith('/')).toBe(true);
    expect(config.baseUrl.endsWith('/')).toBe(true);
  });

  it('keeps onBrokenLinks at warn so the link ratchet, not the build, enforces', () => {
    const config = loadConfig();
    expect(config.onBrokenLinks).toBe('warn');
    expect(config.markdown?.hooks?.onBrokenMarkdownLinks).not.toBe('throw');
  });
});
