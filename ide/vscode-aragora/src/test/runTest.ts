import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { runTests } from '@vscode/test-electron';

// An exact version (never 'stable') keeps runs reproducible and lets them reuse
// the download cached in .vscode-test/.
const VSCODE_VERSION = '1.136.1';

// The extension calls the Aragora API when it activates. The reserved `.invalid`
// domain never resolves, so the run contacts no server and needs no port.
const TEST_USER_SETTINGS = {
  'aragora.apiUrl': 'http://api.aragora.invalid',
  'aragora.autoConnect': false,
  'telemetry.telemetryLevel': 'off',
  'workbench.startupEditor': 'none',
};

async function main(): Promise<void> {
  const extensionDevelopmentPath = path.resolve(__dirname, '../../');
  const extensionTestsPath = path.resolve(__dirname, './suite/index');
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aragora-vscode-test-'));
  fs.mkdirSync(path.join(userDataDir, 'User'));
  fs.writeFileSync(
    path.join(userDataDir, 'User', 'settings.json'),
    JSON.stringify(TEST_USER_SETTINGS, null, 2),
  );

  console.log(`Pinned VS Code version: ${VSCODE_VERSION}`);
  try {
    await runTests({
      version: VSCODE_VERSION,
      extensionDevelopmentPath,
      extensionTestsPath,
      // Without VSCODE_CLI (set when `code` is started from a terminal), VS Code
      // and its agent host spawn the user's login shell to read its environment,
      // and that shell can outlive the test run.
      extensionTestsEnv: { ARAGORA_EXPECTED_VSCODE_VERSION: VSCODE_VERSION, VSCODE_CLI: '1' },
      launchArgs: ['--disable-extensions', `--user-data-dir=${userDataDir}`],
    });
  } finally {
    fs.rmSync(userDataDir, { recursive: true, force: true });
  }
}

main().catch((error: unknown) => {
  console.error('VS Code integration tests failed:', error);
  process.exit(1);
});
