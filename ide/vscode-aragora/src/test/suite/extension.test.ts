import * as assert from 'assert';
import { describe, it } from 'mocha';
import * as vscode from 'vscode';

const EXTENSION_ID = 'aragora.aragora';

describe('Aragora extension in VS Code', () => {
  it('runs in the pinned VS Code version', () => {
    console.log(`VS Code version under test: ${vscode.version}`);
    const expected = process.env.ARAGORA_EXPECTED_VSCODE_VERSION;
    assert.ok(expected, 'ARAGORA_EXPECTED_VSCODE_VERSION is unset; run `npm run test:integration`');
    assert.strictEqual(vscode.version, expected);
  });

  it('activates and registers aragora.* commands', async () => {
    const extension = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(extension, `${EXTENSION_ID} is not loaded in the extension host`);

    // Activation events are language-based, so an empty window never activates
    // the extension on its own.
    await vscode.extensions.getExtension('aragora.aragora')!.activate();
    assert.strictEqual(extension.isActive, true);

    const commands = await vscode.commands.getCommands(true);
    const aragoraCommands = commands.filter((command) => command.startsWith('aragora.'));
    console.log(`Registered aragora.* commands: ${aragoraCommands.length}`);
    assert.ok(aragoraCommands.includes('aragora.runDebate'), 'aragora.runDebate is not registered');
  });
});
