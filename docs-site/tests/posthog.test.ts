import { createRequire } from 'node:module';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);
const CONFIG_PATH = path.resolve(__dirname, '..', 'docusaurus.config.js');

type PluginEntry = string | [string, Record<string, unknown>];

function loadPlugins(): PluginEntry[] {
  delete require.cache[CONFIG_PATH];
  return (require(CONFIG_PATH) as { plugins?: PluginEntry[] }).plugins ?? [];
}

function posthogEntries(plugins: PluginEntry[]): PluginEntry[] {
  return plugins.filter((entry) => {
    const name = Array.isArray(entry) ? entry[0] : entry;
    return typeof name === 'string' && name.includes('posthog');
  });
}

describe('PostHog plugin gating', () => {
  let saved: string | undefined;

  beforeEach(() => {
    saved = process.env.POSTHOG_API_KEY;
    delete process.env.POSTHOG_API_KEY;
  });

  afterEach(() => {
    if (saved === undefined) {
      delete process.env.POSTHOG_API_KEY;
    } else {
      process.env.POSTHOG_API_KEY = saved;
    }
  });

  it('adds no posthog plugin when POSTHOG_API_KEY is unset', () => {
    expect(posthogEntries(loadPlugins())).toEqual([]);
  });

  it('adds no posthog plugin when POSTHOG_API_KEY is empty', () => {
    process.env.POSTHOG_API_KEY = '';
    expect(posthogEntries(loadPlugins())).toEqual([]);
  });
});
