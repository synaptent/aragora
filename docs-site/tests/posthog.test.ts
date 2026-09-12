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

  it('adds exactly one posthog-docusaurus plugin carrying the key when POSTHOG_API_KEY is set', () => {
    process.env.POSTHOG_API_KEY = 'phc_test';
    const plugins = loadPlugins();
    const entries = posthogEntries(plugins);
    expect(entries).toHaveLength(1);
    const [name, options] = entries[0] as [string, Record<string, unknown>];
    expect(name).toBe(require.resolve('posthog-docusaurus'));
    expect(options).toEqual({ apiKey: 'phc_test' });
    // The gate adds to the plugin list; it never replaces the OpenAPI plugin.
    expect(plugins.length).toBe(loadPluginsWithout().length + 1);
  });

  it('keeps the other plugins identical with and without the key', () => {
    const without = loadPluginsWithout().map(pluginName);
    process.env.POSTHOG_API_KEY = 'phc_test';
    const withKey = loadPlugins()
      .map(pluginName)
      .filter((name) => !name.includes('posthog'));
    expect(withKey).toEqual(without);
  });
});

function loadPluginsWithout(): PluginEntry[] {
  const saved = process.env.POSTHOG_API_KEY;
  delete process.env.POSTHOG_API_KEY;
  try {
    return loadPlugins();
  } finally {
    if (saved !== undefined) {
      process.env.POSTHOG_API_KEY = saved;
    }
  }
}

function pluginName(entry: PluginEntry): string {
  return Array.isArray(entry) ? entry[0] : entry;
}
