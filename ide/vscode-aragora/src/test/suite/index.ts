import * as path from 'path';
import Mocha from 'mocha';
import { glob } from 'glob';

// Loaded by VS Code through --extensionTestsPath; runs inside the extension host.
export async function run(): Promise<void> {
  const mocha = new Mocha({ ui: 'bdd', timeout: 60_000 });
  const testsRoot = __dirname;
  const files = (await glob('**/*.test.js', { cwd: testsRoot })).sort();
  if (files.length === 0) {
    throw new Error(`No integration tests found under ${testsRoot}`);
  }
  for (const file of files) {
    mocha.addFile(path.resolve(testsRoot, file));
  }

  const failures = await new Promise<number>((resolve) => mocha.run(resolve));
  if (failures > 0) {
    throw new Error(`${failures} VS Code integration test(s) failed`);
  }
}
