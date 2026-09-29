#!/usr/bin/env node
// Broken-link ratchet for the docs site.
//
// Runs `docusaurus build` (or reads a saved build log), extracts the
// "Exhaustive list of all broken links found" report that Docusaurus prints
// under `onBrokenLinks: 'warn'`, and hands it to the shared shrink-only ratchet
// runner (`scripts/ci/check_tool_baseline.py --tool docs-links`) against
// `scripts/baselines/docs-broken-links.json`. The build keeps succeeding with
// warnings; this gate is what fails when a new broken link appears.

import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO_ROOT = path.resolve(SITE_DIR, '..');
const RUNNER = path.join(REPO_ROOT, 'scripts', 'ci', 'check_tool_baseline.py');
const DEFAULT_BASELINE = path.join(REPO_ROOT, 'scripts', 'baselines', 'docs-broken-links.json');

// 1 (new links) is the shared runner's own exit code, passed through unchanged.
const EXIT_OK = 0;
const EXIT_USAGE = 2;
const EXIT_UNAVAILABLE = 3;

const REPORT_START = 'Exhaustive list of all broken links found:';
const TARGET_LINE = /^\s+-> linking to /;
const BUILD_SUCCEEDED = /\[SUCCESS\] Generated static files/;
const ANSI = new RegExp(`${String.fromCharCode(0x1b)}\\[[0-9;]*[A-Za-z]`, 'g');

const USAGE = `usage: node scripts/check_broken_links.mjs [--log <file>] [--baseline <file>] [--update] [--report-json <file>] [--help]

Ratchet the Docusaurus broken-link report against a shrink-only baseline.

Arguments:
  --log <file>          Read a saved \`npm run build\` / \`docusaurus build\` log
                        instead of building. Without it the script runs
                        \`npx docusaurus build\` in docs-site and captures the log.
  --baseline <file>     Baseline JSON (default: scripts/baselines/docs-broken-links.json,
                        new format: tool "docs-links" + findings keyed
                        <page route>::<link as written>::broken-link).
  --update              Rewrite the baseline to the current set (shrink-only; the
                        shared runner refuses growth without --allow-grow --reason).
  --allow-grow --reason <text>
                        With --update, permit growth and record the reason.
  --report-json <file>  Write the runner's JSON report (new keys, counts, exit code).
  -h, --help            Show this help and exit 0.

Exit codes:
  0  no broken links beyond the baseline (resolved links are fine)
  1  new broken links; each is printed as
     "NEW <page>::<link>::broken-link" with the page and remedies
  2  usage error, or the baseline is missing/corrupt/mismatched
  3  the build failed or the log is unavailable/unreadable (baseline untouched)
`;

function parseArgs(argv) {
  const opts = {
    log: null,
    baseline: DEFAULT_BASELINE,
    update: false,
    allowGrow: false,
    reason: null,
    reportJson: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const value = () => {
      const next = argv[i + 1];
      if (next === undefined) {
        throw new Error(`${arg} requires a value`);
      }
      i += 1;
      return next;
    };
    if (arg === '-h' || arg === '--help') {
      process.stdout.write(USAGE);
      process.exit(EXIT_OK);
    } else if (arg === '--log') {
      opts.log = path.resolve(value());
    } else if (arg === '--baseline') {
      opts.baseline = path.resolve(value());
    } else if (arg === '--update') {
      opts.update = true;
    } else if (arg === '--allow-grow') {
      opts.allowGrow = true;
    } else if (arg === '--reason') {
      opts.reason = value();
    } else if (arg === '--report-json') {
      opts.reportJson = path.resolve(value());
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  return opts;
}

// Runs the build and returns its combined output; null when the build failed.
function buildLog() {
  const result = spawnSync('npx', ['docusaurus', 'build'], {
    cwd: SITE_DIR,
    encoding: 'utf8',
    maxBuffer: 256 * 1024 * 1024,
    env: { ...process.env, FORCE_COLOR: '0', NO_COLOR: '1' },
  });
  const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
  if (result.error) {
    process.stderr.write(`check_broken_links: build failed to start: ${result.error.message}\n`);
    return null;
  }
  if (result.status !== 0) {
    const tail = output.trim().split('\n').slice(-20).join('\n');
    process.stderr.write(
      `check_broken_links: docusaurus build exited ${result.status ?? result.signal}\n${tail}\n`,
    );
    return null;
  }
  return output;
}

export function stripAnsi(text) {
  return text.replace(ANSI, '');
}

// The report block: from the "Exhaustive list" header to the first blank line.
// Docusaurus prints it once per build; a log without it means zero links.
export function extractReport(log) {
  const lines = stripAnsi(log).split(/\r?\n/);
  const start = lines.findIndex((line) => line.trim() === REPORT_START);
  if (start === -1) {
    return '';
  }
  const block = [];
  for (const line of lines.slice(start + 1)) {
    if (line.trim() === '') {
      break;
    }
    block.push(line);
  }
  return block.length ? `${block.join('\n')}\n` : '';
}

export function countTargets(report) {
  return report.split('\n').filter((line) => TARGET_LINE.test(line)).length;
}

function runRatchet(report, opts) {
  const scratch = mkdtempSync(path.join(tmpdir(), 'docs-links-'));
  const reportPath = path.join(scratch, 'broken-links.txt');
  writeFileSync(reportPath, report, 'utf8');
  const args = [RUNNER, '--tool', 'docs-links', '--cwd', SITE_DIR, '--baseline', opts.baseline];
  if (opts.update) args.push('--update');
  if (opts.allowGrow) args.push('--allow-grow');
  if (opts.reason !== null) args.push('--reason', opts.reason);
  if (opts.reportJson) args.push('--report-json', opts.reportJson);
  // The runner re-reads the captured report through `cat`, so the parser sees
  // exactly the block extracted above and nothing else from the build log.
  args.push('--', 'cat', reportPath);
  try {
    const result = spawnSync('python3', args, { cwd: REPO_ROOT, stdio: 'inherit' });
    if (result.error) {
      process.stderr.write(`check_broken_links: cannot run ${RUNNER}: ${result.error.message}\n`);
      return EXIT_UNAVAILABLE;
    }
    return result.status ?? EXIT_UNAVAILABLE;
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`check_broken_links: ${error.message}\n${USAGE}`);
    return EXIT_USAGE;
  }

  let log;
  if (opts.log) {
    if (!existsSync(opts.log)) {
      process.stderr.write(`check_broken_links: log not found: ${opts.log}\n`);
      return EXIT_UNAVAILABLE;
    }
    try {
      log = readFileSync(opts.log, 'utf8');
    } catch (error) {
      process.stderr.write(`check_broken_links: cannot read ${opts.log}: ${error.message}\n`);
      return EXIT_UNAVAILABLE;
    }
    if (!BUILD_SUCCEEDED.test(stripAnsi(log))) {
      process.stderr.write(
        `check_broken_links: ${opts.log} is not a successful docusaurus build log\n`,
      );
      return EXIT_UNAVAILABLE;
    }
  } else {
    log = buildLog();
    if (log === null) {
      return EXIT_UNAVAILABLE;
    }
  }

  const report = extractReport(log);
  process.stdout.write(
    `check_broken_links: ${countTargets(report)} broken link target(s) in the build report\n`,
  );
  return runRatchet(report, opts);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main());
}
