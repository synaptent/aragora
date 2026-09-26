/**
 * Aragora Review Panel
 *
 * Webview panel for code review results with inline annotations and suggested fixes.
 * Following Kilocode's pattern for code review visualization.
 */

import * as vscode from 'vscode';
import type {
  ExtensionMessage,
  WebviewMessage,
  ReviewResult,
  ReviewComment,
  Agent,
  CodeLocation,
  Severity,
} from '../types/messages';

type AragoraClient = {
  reviewCode(content: string, languageId: string, fileName: string): Promise<ReviewResult>;
};

export class ReviewPanel {
  public static currentPanel: ReviewPanel | undefined;
  public static readonly viewType = 'aragora.reviewPanel';

  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private disposables: vscode.Disposable[] = [];
  private review: ReviewResult | null = null;
  private sourceUri: vscode.Uri | null = null;
  private client: AragoraClient | null = null;

  private constructor(
    panel: vscode.WebviewPanel,
    extensionUri: vscode.Uri,
    client?: AragoraClient,
  ) {
    this.panel = panel;
    this.extensionUri = extensionUri;
    this.client = client || null;

    // Set webview content
    this.panel.webview.html = this.getHtmlContent();

    // Handle panel disposal
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

    // Handle messages from webview
    this.panel.webview.onDidReceiveMessage(
      (message: WebviewMessage) => this.handleWebviewMessage(message),
      null,
      this.disposables,
    );
  }

  /**
   * Create or show the review panel
   */
  public static createOrShow(extensionUri: vscode.Uri, client?: AragoraClient): ReviewPanel {
    const column = vscode.ViewColumn.Beside;

    // If we already have a panel, show it
    if (ReviewPanel.currentPanel) {
      ReviewPanel.currentPanel.panel.reveal(column);
      return ReviewPanel.currentPanel;
    }

    // Create a new panel
    const panel = vscode.window.createWebviewPanel(ReviewPanel.viewType, 'Aragora Review', column, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'webview-ui', 'dist')],
    });

    ReviewPanel.currentPanel = new ReviewPanel(panel, extensionUri, client);
    return ReviewPanel.currentPanel;
  }

  /**
   * Start a review of code
   */
  public async startReview(uri: vscode.Uri, range?: vscode.Range): Promise<void> {
    this.sourceUri = uri;

    const document = await vscode.workspace.openTextDocument(uri);
    const content = range ? document.getText(range) : document.getText();
    const fileName = uri.fsPath.split('/').pop() || 'unknown';

    this.review = {
      id: `review-${Date.now()}`,
      file: uri.fsPath,
      status: 'in_progress',
      comments: [],
      summary: '',
      agents: [],
    };

    this.postMessage({ type: 'review_started', review: this.review });

    this.panel.title = `Review: ${fileName}`;

    // If we have a client, run the actual review
    if (this.client) {
      try {
        const result = await this.client.reviewCode(content, document.languageId, fileName);
        this.review = result;
        this.postMessage({ type: 'review_completed', review: result });
      } catch (error) {
        // Use mock review for development
        await this.runMockReview(content, document.languageId, range?.start.line || 0);
      }
    } else {
      // Use mock review
      await this.runMockReview(content, document.languageId, range?.start.line || 0);
    }
  }

  /**
   * Run a mock review for development/demo
   */
  private async runMockReview(
    content: string,
    languageId: string,
    startLine: number,
  ): Promise<void> {
    if (!this.review || !this.sourceUri) return;

    const agents: Agent[] = [
      { id: 'claude', name: 'Claude', provider: 'anthropic', color: '#C97539' },
      { id: 'gpt-4', name: 'GPT-4', provider: 'openai', color: '#10A37F' },
    ];

    this.review.agents = agents;

    // Simulate streaming comments
    const mockComments = this.generateMockComments(content, languageId, startLine);

    for (const comment of mockComments) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      this.review.comments.push(comment);
      this.postMessage({ type: 'review_comment', comment });
    }

    // Complete the review
    this.review.status = 'completed';
    this.review.summary = this.generateSummary(mockComments);
    this.review.overallScore = Math.max(
      0,
      100 -
        mockComments.filter((c) => c.severity === 'high' || c.severity === 'critical').length * 15 -
        mockComments.filter((c) => c.severity === 'medium').length * 5,
    );

    this.postMessage({ type: 'review_completed', review: this.review });
  }

  private generateMockComments(
    content: string,
    languageId: string,
    startLine: number,
  ): ReviewComment[] {
    const comments: ReviewComment[] = [];
    const lines = content.split('\n');

    lines.forEach((line, index) => {
      const lineNumber = startLine + index + 1;

      // Check for various issues
      if (/console\.(log|debug|info)\s*\(/.test(line)) {
        comments.push({
          id: `comment-${Date.now()}-${index}`,
          agent: { id: 'claude', name: 'Claude', provider: 'anthropic' },
          content:
            'Consider removing console statements before production deployment, or replace with a proper logging framework.',
          location: {
            file: this.sourceUri?.fsPath || '',
            line: lineNumber,
            column: line.indexOf('console'),
          },
          severity: 'low',
          category: 'style',
        });
      }

      if (/\bany\b/.test(line) && languageId.includes('typescript')) {
        comments.push({
          id: `comment-${Date.now()}-${index}-any`,
          agent: { id: 'gpt-4', name: 'GPT-4', provider: 'openai' },
          content:
            'Using `any` defeats the purpose of TypeScript. Consider using a more specific type or `unknown` if the type is truly unknown.',
          location: {
            file: this.sourceUri?.fsPath || '',
            line: lineNumber,
            column: line.indexOf('any'),
          },
          severity: 'medium',
          category: 'suggestion',
          suggestedFix: { oldCode: 'any', newCode: 'unknown' },
        });
      }

      if (/catch\s*\(\s*\w*\s*\)\s*\{\s*\}/.test(line)) {
        comments.push({
          id: `comment-${Date.now()}-${index}-catch`,
          agent: { id: 'claude', name: 'Claude', provider: 'anthropic' },
          content:
            'Empty catch blocks swallow errors silently. At minimum, log the error for debugging.',
          location: {
            file: this.sourceUri?.fsPath || '',
            line: lineNumber,
            column: line.indexOf('catch'),
          },
          severity: 'high',
          category: 'bug',
          suggestedFix: {
            oldCode: 'catch (e) {}',
            newCode: 'catch (e) { console.error("Error:", e); }',
          },
        });
      }

      if (/==(?!=)/.test(line) && !line.includes('===')) {
        comments.push({
          id: `comment-${Date.now()}-${index}-eq`,
          agent: { id: 'gpt-4', name: 'GPT-4', provider: 'openai' },
          content:
            'Use strict equality (===) instead of loose equality (==) to avoid type coercion bugs.',
          location: {
            file: this.sourceUri?.fsPath || '',
            line: lineNumber,
            column: line.indexOf('=='),
          },
          severity: 'medium',
          category: 'bug',
        });
      }

      if (/function\s+\w+\s*\([^)]{60,}\)/.test(line)) {
        comments.push({
          id: `comment-${Date.now()}-${index}-params`,
          agent: { id: 'claude', name: 'Claude', provider: 'anthropic' },
          content:
            'Functions with many parameters are hard to use and maintain. Consider using an options object instead.',
          location: { file: this.sourceUri?.fsPath || '', line: lineNumber, column: 0 },
          severity: 'low',
          category: 'suggestion',
        });
      }
    });

    // Add a praise comment if code looks good
    if (comments.length < 3) {
      comments.push({
        id: `comment-${Date.now()}-praise`,
        agent: { id: 'gpt-4', name: 'GPT-4', provider: 'openai' },
        content: 'Overall clean code structure with good readability. Keep up the good work!',
        location: { file: this.sourceUri?.fsPath || '', line: startLine + 1, column: 0 },
        severity: 'info',
        category: 'praise',
      });
    }

    return comments;
  }

  private generateSummary(comments: ReviewComment[]): string {
    const byCategory: Record<string, number> = {};
    for (const comment of comments) {
      byCategory[comment.category] = (byCategory[comment.category] || 0) + 1;
    }

    const parts: string[] = [];
    const total = comments.length;
    const issues = comments.filter((c) => c.category !== 'praise').length;

    if (issues === 0) {
      parts.push('No significant issues found in this code.');
    } else {
      parts.push(
        `Found ${issues} issue${issues !== 1 ? 's' : ''} across ${total} comment${total !== 1 ? 's' : ''}.`,
      );
    }

    if (byCategory.security) {
      parts.push(`${byCategory.security} security concern${byCategory.security !== 1 ? 's' : ''}.`);
    }
    if (byCategory.bug) {
      parts.push(`${byCategory.bug} potential bug${byCategory.bug !== 1 ? 's' : ''}.`);
    }
    if (byCategory.performance) {
      parts.push(
        `${byCategory.performance} performance suggestion${byCategory.performance !== 1 ? 's' : ''}.`,
      );
    }

    return parts.join(' ');
  }

  private handleWebviewMessage(message: WebviewMessage): void {
    switch (message.type) {
      case 'ready':
        if (this.review) {
          this.postMessage({
            type: 'state_sync',
            state: {
              debates: [],
              reviews: [this.review],
              findings: [],
              settings: this.getSettings(),
              connectionStatus: 'connected',
            },
          });
        }
        break;

      case 'apply_fix':
        this.applyFix(message.commentId);
        break;

      case 'apply_all_fixes':
        this.applyAllFixes();
        break;

      case 'dismiss_comment':
        this.dismissComment(message.commentId);
        break;

      case 'navigate_to_comment':
        this.navigateToComment(message.commentId);
        break;
    }
  }

  private async applyFix(commentId: string): Promise<void> {
    if (!this.review || !this.sourceUri) return;

    const comment = this.review.comments.find((c) => c.id === commentId);
    if (!comment?.suggestedFix) return;

    const document = await vscode.workspace.openTextDocument(this.sourceUri);
    const editor = await vscode.window.showTextDocument(document);

    const line = document.lineAt(comment.location.line - 1);
    const oldText = comment.suggestedFix.oldCode;
    const newText = comment.suggestedFix.newCode;

    const startIndex = line.text.indexOf(oldText);
    if (startIndex === -1) return;

    const range = new vscode.Range(
      comment.location.line - 1,
      startIndex,
      comment.location.line - 1,
      startIndex + oldText.length,
    );

    await editor.edit((editBuilder) => {
      editBuilder.replace(range, newText);
    });

    // Mark as resolved
    comment.isResolved = true;
    this.postMessage({ type: 'review_comment', comment });

    vscode.window.showInformationMessage('Fix applied');
  }

  private async applyAllFixes(): Promise<void> {
    if (!this.review) return;

    const fixableComments = this.review.comments.filter((c) => c.suggestedFix && !c.isResolved);

    if (fixableComments.length === 0) {
      vscode.window.showInformationMessage('No fixes to apply');
      return;
    }

    const choice = await vscode.window.showWarningMessage(
      `Apply ${fixableComments.length} fixes?`,
      'Yes, Apply All',
      'Cancel',
    );

    if (choice !== 'Yes, Apply All') return;

    // Sort by line number descending to avoid offset issues
    const sorted = [...fixableComments].sort((a, b) => b.location.line - a.location.line);

    for (const comment of sorted) {
      await this.applyFix(comment.id);
    }

    vscode.window.showInformationMessage(`Applied ${fixableComments.length} fixes`);
  }

  private dismissComment(commentId: string): void {
    if (!this.review) return;

    const comment = this.review.comments.find((c) => c.id === commentId);
    if (comment) {
      comment.isResolved = true;
      this.postMessage({ type: 'review_comment', comment });
    }
  }

  private async navigateToComment(commentId: string): Promise<void> {
    if (!this.review || !this.sourceUri) return;

    const comment = this.review.comments.find((c) => c.id === commentId);
    if (!comment) return;

    const document = await vscode.workspace.openTextDocument(this.sourceUri);
    const editor = await vscode.window.showTextDocument(document, {
      viewColumn: vscode.ViewColumn.One,
    });

    const range = new vscode.Range(
      comment.location.line - 1,
      comment.location.column,
      comment.location.line - 1,
      comment.location.column + 10,
    );

    editor.selection = new vscode.Selection(range.start, range.end);
    editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
  }

  private getSettings() {
    const config = vscode.workspace.getConfiguration('aragora');
    return {
      apiUrl: config.get<string>('apiUrl') || 'https://api.aragora.ai',
      defaultAgents: (config.get<string>('defaultAgents') || 'claude,gpt-4').split(','),
      defaultRounds: config.get<number>('defaultRounds') || 3,
      autoAnalyze: config.get<boolean>('analyzeOnSave', true),
      showInlineHints: config.get<boolean>('showInlineHints', true),
      theme: 'auto' as const,
    };
  }

  private postMessage(message: ExtensionMessage): void {
    this.panel.webview.postMessage(message);
  }

  private getHtmlContent(): string {
    const webview = this.panel.webview;
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, 'webview-ui', 'dist', 'main.js'),
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, 'webview-ui', 'dist', 'main.css'),
    );

    const nonce = this.getNonce();

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; img-src ${webview.cspSource} https: data:;">
  <link href="${styleUri}" rel="stylesheet">
  <title>Aragora Review</title>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    window.vscodeApi = vscode;
    window.initialView = 'review';
  </script>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }

  private getNonce(): string {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
      text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
  }

  public dispose(): void {
    ReviewPanel.currentPanel = undefined;
    this.panel.dispose();
    this.disposables.forEach((d) => d.dispose());
  }
}

/**
 * Register review panel commands
 */
export function registerReviewPanelCommands(
  context: vscode.ExtensionContext,
  client?: AragoraClient,
): void {
  // Show review panel
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'aragora.showReviewPanel',
      async (uri?: vscode.Uri, range?: vscode.Range, options?: { focus?: string }) => {
        const panel = ReviewPanel.createOrShow(context.extensionUri, client);

        // If URI provided, start review
        if (uri) {
          await panel.startReview(uri, range);
        } else {
          // Use active editor
          const editor = vscode.window.activeTextEditor;
          if (editor) {
            const selection = editor.selection;
            await panel.startReview(editor.document.uri, selection.isEmpty ? undefined : selection);
          }
        }
      },
    ),
  );

  // Quick review from editor
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.quickReview', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showErrorMessage('No active editor');
        return;
      }

      const selection = editor.selection;
      const panel = ReviewPanel.createOrShow(context.extensionUri, client);
      await panel.startReview(editor.document.uri, selection.isEmpty ? undefined : selection);
    }),
  );
}
