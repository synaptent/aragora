/**
 * Aragora Code Actions Provider
 *
 * Provides lightbulb actions (Quick Fixes) for code analysis and multi-agent operations.
 * Following the Kilocode pattern for contextual code actions.
 */

import * as vscode from 'vscode';
import type { SecurityFinding } from '../types/messages';

type AragoraClient = {
  analyzeSelection(content: string, languageId: string): Promise<{ explanation: string }>;
  generateTests(content: string, languageId: string): Promise<{ tests: string }>;
  suggestFix(finding: SecurityFinding, content: string): Promise<{ fix: string }>;
};

export class AragoraCodeActionsProvider implements vscode.CodeActionProvider {
  public static readonly providedCodeActionKinds = [
    vscode.CodeActionKind.QuickFix,
    vscode.CodeActionKind.Refactor,
    vscode.CodeActionKind.Source,
  ];

  private diagnosticsProvider: { getFindings(uri: vscode.Uri): SecurityFinding[] } | null = null;
  private client: AragoraClient | null = null;

  constructor(options?: {
    diagnosticsProvider?: { getFindings(uri: vscode.Uri): SecurityFinding[] };
    client?: AragoraClient;
  }) {
    this.diagnosticsProvider = options?.diagnosticsProvider || null;
    this.client = options?.client || null;
  }

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext,
    _token: vscode.CancellationToken,
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];

    // === Always Available Actions ===

    // Explain Code - available when there's any selection or cursor position
    actions.push(
      this.createCommandAction(
        '$(lightbulb) Explain Code',
        'aragora.explainCode',
        [document.uri, range],
        vscode.CodeActionKind.Source,
        'Get a multi-agent explanation of this code',
      ),
    );

    // === Selection-Based Actions ===
    if (!range.isEmpty) {
      // Review Selection
      actions.push(
        this.createCommandAction(
          '$(eye) Review Selection',
          'aragora.reviewSelection',
          [document.uri, range],
          vscode.CodeActionKind.Source,
          'Run multi-agent code review on selection',
        ),
      );

      // Add to Debate Context
      actions.push(
        this.createCommandAction(
          '$(comment-discussion) Add to Debate',
          'aragora.addToDebate',
          [document.uri, range],
          vscode.CodeActionKind.Source,
          'Include this code in debate context',
        ),
      );

      // Generate Tests
      actions.push(
        this.createCommandAction(
          '$(beaker) Generate Tests',
          'aragora.generateTests',
          [document.uri, range],
          vscode.CodeActionKind.Source,
          'Generate tests for selected code',
        ),
      );

      // Improve Code
      actions.push(
        this.createCommandAction(
          '$(sparkle) Improve Code',
          'aragora.improveCode',
          [document.uri, range],
          vscode.CodeActionKind.Refactor,
          'Suggest improvements using multi-agent review',
        ),
      );
    }

    // === Diagnostic-Based Actions ===
    if (context.diagnostics.length > 0) {
      const aragoraDiagnostics = context.diagnostics.filter((d) => d.source === 'Aragora');

      for (const diagnostic of aragoraDiagnostics) {
        // Fix Issue action for each Aragora diagnostic
        const fixAction = this.createCommandAction(
          `$(wrench) Fix: ${this.truncate(diagnostic.message, 40)}`,
          'aragora.fixIssue',
          [document.uri, diagnostic],
          vscode.CodeActionKind.QuickFix,
          'Apply AI-suggested fix',
        );
        fixAction.diagnostics = [diagnostic];
        fixAction.isPreferred = true;
        actions.push(fixAction);

        // Explain Issue
        const explainAction = this.createCommandAction(
          `$(question) Explain Issue`,
          'aragora.explainIssue',
          [document.uri, diagnostic],
          vscode.CodeActionKind.QuickFix,
          'Get detailed explanation of this issue',
        );
        explainAction.diagnostics = [diagnostic];
        actions.push(explainAction);
      }

      // Fix All Aragora Issues
      if (aragoraDiagnostics.length > 1) {
        actions.push(
          this.createCommandAction(
            `$(checklist) Fix All Aragora Issues (${aragoraDiagnostics.length})`,
            'aragora.fixAllIssues',
            [document.uri],
            vscode.CodeActionKind.QuickFix,
            `Fix all ${aragoraDiagnostics.length} Aragora-detected issues`,
          ),
        );
      }
    }

    // === Context-Specific Actions ===

    // If on a function definition, offer specific actions
    const lineText = document.lineAt(range.start.line).text;
    if (this.isFunctionDefinition(lineText, document.languageId)) {
      actions.push(
        this.createCommandAction(
          '$(symbol-method) Document Function',
          'aragora.documentFunction',
          [document.uri, range],
          vscode.CodeActionKind.Refactor,
          'Generate documentation using multi-agent analysis',
        ),
      );

      actions.push(
        this.createCommandAction(
          '$(beaker) Test This Function',
          'aragora.generateTests',
          [document.uri, range],
          vscode.CodeActionKind.Source,
          'Generate comprehensive tests for this function',
        ),
      );
    }

    // If in a test file, offer test-specific actions
    if (this.isTestFile(document.fileName)) {
      actions.push(
        this.createCommandAction(
          '$(debug-alt) Analyze Test Coverage',
          'aragora.analyzeTestCoverage',
          [document.uri, range],
          vscode.CodeActionKind.Source,
          'Analyze what this test covers',
        ),
      );
    }

    return actions;
  }

  private createCommandAction(
    title: string,
    command: string,
    args: unknown[],
    kind: vscode.CodeActionKind,
    tooltip?: string,
  ): vscode.CodeAction {
    const action = new vscode.CodeAction(title, kind);
    action.command = { command, title, arguments: args };
    if (tooltip) {
      action.command.tooltip = tooltip;
    }
    return action;
  }

  private isFunctionDefinition(line: string, languageId: string): boolean {
    // JavaScript/TypeScript
    if (languageId.includes('script') || languageId.includes('typescript')) {
      return /(?:function\s+\w+|(?:async\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>|(?:async\s+)?\w+\s*\([^)]*\)\s*\{)/.test(
        line,
      );
    }
    // Python
    if (languageId === 'python') {
      return /^\s*(?:async\s+)?def\s+\w+/.test(line);
    }
    // Java/C#/Go
    if (['java', 'csharp', 'go'].includes(languageId)) {
      return /(?:public|private|protected|func)\s+\w+/.test(line);
    }
    // Rust
    if (languageId === 'rust') {
      return /(?:pub\s+)?(?:async\s+)?fn\s+\w+/.test(line);
    }
    return false;
  }

  private isTestFile(fileName: string): boolean {
    const testPatterns = [
      /\.test\.[jt]sx?$/,
      /\.spec\.[jt]sx?$/,
      /_test\.go$/,
      /_test\.py$/,
      /test_.*\.py$/,
      /Test\.java$/,
      /Tests?\.cs$/,
    ];
    return testPatterns.some((pattern) => pattern.test(fileName));
  }

  private truncate(text: string, maxLength: number): string {
    // Remove severity icon if present
    const cleaned = text.replace(/^[🔴🟠🟡🔵ℹ️]\s*/, '');
    if (cleaned.length <= maxLength) {
      return cleaned;
    }
    return cleaned.substring(0, maxLength - 3) + '...';
  }

  /**
   * Resolve a code action with additional details (optional)
   */
  resolveCodeAction(
    codeAction: vscode.CodeAction,
    _token: vscode.CancellationToken,
  ): vscode.CodeAction {
    // Could add edit previews here if needed
    return codeAction;
  }
}

/**
 * Register code actions commands
 */
export function registerCodeActionsCommands(
  context: vscode.ExtensionContext,
  client: AragoraClient,
): void {
  // Explain Code
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.explainCode',
      async (uri: vscode.Uri, range: vscode.Range) => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;

        const selection = range.isEmpty ? editor.selection : range;
        const text = editor.document.getText(selection);

        if (!text.trim()) {
          vscode.window.showWarningMessage('Please select some code to explain');
          return;
        }

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: 'Aragora: Explaining Code',
            cancellable: false,
          },
          async () => {
            try {
              const result = await client.analyzeSelection(text, editor.document.languageId);
              // Show in a new document
              const doc = await vscode.workspace.openTextDocument({
                content: `# Code Explanation\n\n${result.explanation}`,
                language: 'markdown',
              });
              await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside });
            } catch (error) {
              vscode.window.showErrorMessage(`Failed to explain code: ${error}`);
            }
          },
        );
      },
    ),
  );

  // Review Selection
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.reviewSelection',
      async (uri: vscode.Uri, range: vscode.Range) => {
        // This will be implemented by the ReviewPanel
        vscode.commands.executeCommand('aragora.showReviewPanel', uri, range);
      },
    ),
  );

  // Add to Debate
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.addToDebate',
      async (uri: vscode.Uri, range: vscode.Range) => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;

        const text = editor.document.getText(range);
        const fileName = editor.document.fileName.split('/').pop();

        // Store in workspace state for debate context
        const existingContext = context.workspaceState.get<string[]>('debateContext', []);
        existingContext.push(
          `\n### From ${fileName} (lines ${range.start.line + 1}-${range.end.line + 1}):\n\`\`\`\n${text}\n\`\`\``,
        );
        await context.workspaceState.update('debateContext', existingContext);

        vscode.window.showInformationMessage(
          `Added ${text.split('\n').length} lines to debate context (${existingContext.length} snippets total)`,
        );
      },
    ),
  );

  // Generate Tests
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.generateTests',
      async (uri: vscode.Uri, range: vscode.Range) => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;

        const selection = range.isEmpty ? editor.selection : range;
        const text = editor.document.getText(selection);

        if (!text.trim()) {
          vscode.window.showWarningMessage('Please select code to generate tests for');
          return;
        }

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: 'Aragora: Generating Tests',
            cancellable: false,
          },
          async () => {
            try {
              const result = await client.generateTests(text, editor.document.languageId);
              // Create a new test file
              const testDoc = await vscode.workspace.openTextDocument({
                content: result.tests,
                language: editor.document.languageId,
              });
              await vscode.window.showTextDocument(testDoc, {
                viewColumn: vscode.ViewColumn.Beside,
              });
            } catch (error) {
              vscode.window.showErrorMessage(`Failed to generate tests: ${error}`);
            }
          },
        );
      },
    ),
  );

  // Improve Code
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.improveCode',
      async (uri: vscode.Uri, range: vscode.Range) => {
        // Opens the review panel with improvement focus
        vscode.commands.executeCommand('aragora.showReviewPanel', uri, range, {
          focus: 'improvement',
        });
      },
    ),
  );

  // Fix Issue
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.fixIssue',
      async (uri: vscode.Uri, diagnostic: vscode.Diagnostic) => {
        const editor = await vscode.window.showTextDocument(uri);

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: 'Aragora: Generating Fix',
            cancellable: false,
          },
          async () => {
            try {
              // Get the line content
              const line = editor.document.lineAt(diagnostic.range.start.line);
              const finding: SecurityFinding = {
                id: diagnostic.code?.toString() || 'unknown',
                title: diagnostic.message.split(':')[0] || 'Issue',
                description: diagnostic.message,
                severity: 'medium',
                category: 'security',
                location: {
                  file: uri.fsPath,
                  line: diagnostic.range.start.line + 1,
                  column: diagnostic.range.start.character,
                },
              };

              const result = await client.suggestFix(finding, line.text);

              // Apply the fix
              await editor.edit((editBuilder) => {
                editBuilder.replace(line.range, result.fix);
              });

              vscode.window.showInformationMessage('Fix applied');
            } catch (error) {
              vscode.window.showErrorMessage(`Failed to apply fix: ${error}`);
            }
          },
        );
      },
    ),
  );

  // Explain Issue
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.explainIssue',
      async (uri: vscode.Uri, diagnostic: vscode.Diagnostic) => {
        const explanation = `# Issue Explanation\n\n**${diagnostic.message}**\n\nSeverity: ${diagnostic.severity}\nSource: ${diagnostic.source}\nCode: ${diagnostic.code}\n\n${diagnostic.relatedInformation?.map((i) => i.message).join('\n') || ''}`;

        const doc = await vscode.workspace.openTextDocument({
          content: explanation,
          language: 'markdown',
        });
        await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside });
      },
    ),
  );

  // Fix All Issues
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.fixAllIssues', async (uri: vscode.Uri) => {
      const diagnostics = vscode.languages
        .getDiagnostics(uri)
        .filter((d) => d.source === 'Aragora');

      if (diagnostics.length === 0) {
        vscode.window.showInformationMessage('No Aragora issues to fix');
        return;
      }

      const choice = await vscode.window.showWarningMessage(
        `Apply fixes for ${diagnostics.length} issues?`,
        'Yes, Fix All',
        'Cancel',
      );

      if (choice !== 'Yes, Fix All') return;

      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: 'Aragora: Fixing All Issues',
          cancellable: false,
        },
        async (progress) => {
          let fixed = 0;
          for (const diagnostic of diagnostics) {
            try {
              await vscode.commands.executeCommand('aragora.fixIssue', uri, diagnostic);
              fixed++;
              progress.report({
                message: `Fixed ${fixed}/${diagnostics.length}`,
                increment: (1 / diagnostics.length) * 100,
              });
            } catch (error) {
              console.error(`Failed to fix issue: ${error}`);
            }
          }
          vscode.window.showInformationMessage(`Fixed ${fixed}/${diagnostics.length} issues`);
        },
      );
    }),
  );

  // Document Function
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.documentFunction',
      async (uri: vscode.Uri, range: vscode.Range) => {
        // Similar to explainCode but formats as documentation
        vscode.commands.executeCommand('aragora.explainCode', uri, range);
      },
    ),
  );

  // Analyze Test Coverage
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.analyzeTestCoverage',
      async (uri: vscode.Uri, range: vscode.Range) => {
        vscode.window.showInformationMessage('Test coverage analysis coming soon!');
      },
    ),
  );
}
