/** @jest-environment node */

import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';

const script = resolve(__dirname, '../../..', 'scripts/check_dead_flags.mjs');

describe('dead-flag CLI', () => {
  let fixture: string;
  let src: string;
  const write = (path: string, text: string) => {
    const target = join(src, path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, text);
  };
  const run = (...args: string[]) =>
    spawnSync(process.execPath, [script, ...args], { encoding: 'utf8', timeout: 10000 });

  beforeEach(() => {
    fixture = mkdtempSync(join(tmpdir(), 'live-dead-flags-'));
    src = join(fixture, 'src');
    write('lib/flags.ts', 'export const flags = { active: false, unused: false } as const;');
  });

  afterEach(() => {
    rmSync(fixture, { recursive: true, force: true });
  });

  it('documents arguments and exit codes in --help', () => {
    const result = run('--help');
    expect(result.status).toBe(0);
    expect(result.stdout).toContain('--src-dir');
    expect(result.stdout).toMatch(/0.*referenced/);
    expect(result.stdout).toMatch(/1.*unreferenced/);
    expect(result.stdout).toMatch(/2.*error/);
  });

  it('names unreferenced flags, ignoring declarations, tests, comments and strings', () => {
    write('view.ts', "import { flags } from './lib/flags'; flags.active; // flags.unused");
    write('lib/__tests__/flags.test.ts', 'flags.unused;');
    write('lib/flags.test.ts', 'flags.unused;');
    write('text.ts', 'const text = "flags.unused";');
    const result = run('--src-dir', src);
    expect(result.status).toBe(1);
    expect(result.stdout).toContain('unused');
    expect(result.stdout).not.toContain('dead flag: active');
  });

  it('recognizes dot and literal bracket references, including imported aliases', () => {
    write(
      'nested/view.tsx',
      "import { flags as rollout } from '../lib/flags'; rollout.active; rollout['unused'];",
    );
    const result = run('--src-dir', src);
    expect(result.status).toBe(0);
    expect(result.stdout).toContain('2 flags, all referenced');
  });

  it('does not count a different flags object as a reference', () => {
    write('other.ts', 'const flags = { active: true, unused: true }; flags.active; flags.unused;');
    expect(run('--src-dir', src).status).toBe(1);
  });

  it.each([['--unknown'], ['--src-dir']])('rejects invalid arguments %s', (...args) => {
    const result = run(...args);
    expect(result.status).toBe(2);
    expect(result.stderr).toContain('error');
  });

  it('fails closed when the flag declaration is missing or not a literal object', () => {
    write('lib/flags.ts', 'export const flags = getFlags();');
    expect(run('--src-dir', src).status).toBe(2);
    write('lib/flags.ts', 'export const somethingElse = {};');
    expect(run('--src-dir', src).status).toBe(2);
  });

  it('fails closed for unreadable source directories and invalid TypeScript', () => {
    expect(run('--src-dir', join(fixture, 'missing')).status).toBe(2);
    write('lib/flags.ts', 'export const flags = { broken:');
    expect(run('--src-dir', src).status).toBe(2);
  });
});
