/**
 * Aragora Debate Panel
 *
 * Webview panel for visualizing multi-agent debates with chat-style interface.
 * Following Kilocode's ChatView pattern for streaming messages.
 */

import * as vscode from 'vscode';
import type {
  ExtensionMessage,
  WebviewMessage,
  DebateState,
  DebateMessage,
  DebateConsensus,
  Agent,
  getAgentColor,
} from '../types/messages';
import type { StreamManager } from '../services/StreamManager';
import { getLogger } from '../logger';

const logger = getLogger();

export class DebatePanel {
  public static currentPanel: DebatePanel | undefined;
  public static readonly viewType = 'aragora.debatePanel';

  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private disposables: vscode.Disposable[] = [];
  private debate: DebateState | null = null;
  private streamManager: StreamManager | null = null;

  private constructor(
    panel: vscode.WebviewPanel,
    extensionUri: vscode.Uri,
    streamManager?: StreamManager,
  ) {
    this.panel = panel;
    this.extensionUri = extensionUri;
    this.streamManager = streamManager || null;

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

    // Subscribe to stream events
    if (this.streamManager) {
      this.disposables.push(this.streamManager.subscribe((event) => this.handleStreamEvent(event)));
    }
  }

  /**
   * Create or show the debate panel
   */
  public static createOrShow(extensionUri: vscode.Uri, streamManager?: StreamManager): DebatePanel {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    // If we already have a panel, show it
    if (DebatePanel.currentPanel) {
      DebatePanel.currentPanel.panel.reveal(column);
      return DebatePanel.currentPanel;
    }

    // Create a new panel
    const panel = vscode.window.createWebviewPanel(
      DebatePanel.viewType,
      'Aragora Debate',
      column || vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'webview-ui', 'dist')],
      },
    );

    DebatePanel.currentPanel = new DebatePanel(panel, extensionUri, streamManager);
    return DebatePanel.currentPanel;
  }

  /**
   * Start a new debate
   */
  public startDebate(question: string, agents: string[], rounds: number): void {
    this.debate = {
      id: `debate-${Date.now()}`,
      question,
      status: 'pending',
      currentRound: 0,
      totalRounds: rounds,
      messages: [],
      startTime: Date.now(),
    };

    this.postMessage({ type: 'debate_started', debate: this.debate });

    // Update title
    this.panel.title = `Debate: ${question.substring(0, 30)}...`;
  }

  /**
   * Add a message to the debate
   */
  public addMessage(message: DebateMessage): void {
    if (this.debate) {
      this.debate.messages.push(message);
      this.debate.currentRound = message.round;
      this.debate.status = 'running';
    }

    this.postMessage({ type: 'agent_message', message });
  }

  /**
   * Set the consensus
   */
  public setConsensus(consensus: DebateConsensus): void {
    if (this.debate) {
      this.debate.consensus = consensus;
      this.debate.status = 'completed';
      this.debate.endTime = Date.now();
    }

    this.postMessage({ type: 'consensus_reached', consensus });
  }

  /**
   * Update the entire debate state
   */
  public updateDebate(debate: DebateState): void {
    this.debate = debate;
    this.postMessage({ type: 'debate_updated', debate });
  }

  private handleWebviewMessage(message: WebviewMessage): void {
    switch (message.type) {
      case 'ready':
        // Send current state to webview
        if (this.debate) {
          this.postMessage({
            type: 'state_sync',
            state: {
              debates: [this.debate],
              reviews: [],
              findings: [],
              settings: this.getSettings(),
              connectionStatus: this.streamManager?.getConnectionStatus() || 'disconnected',
            },
          });
        }
        break;

      case 'copy_result':
        if (this.debate?.consensus) {
          vscode.env.clipboard.writeText(this.debate.consensus.answer);
          vscode.window.showInformationMessage('Consensus copied to clipboard');
        }
        break;

      case 'export_debate':
        this.exportDebate(message.format);
        break;

      case 'send_feedback':
        this.sendFeedback(message.vote, message.comment);
        break;

      case 'start_debate':
        vscode.commands.executeCommand('aragora.runDebate');
        break;

      case 'stop_debate':
        if (this.debate) {
          this.debate.status = 'failed';
          this.postMessage({
            type: 'debate_failed',
            debateId: this.debate.id,
            error: 'Debate stopped by user',
          });
        }
        break;
    }
  }

  private handleStreamEvent(event: ExtensionMessage): void {
    // Forward relevant events to webview
    if (
      event.type === 'agent_message' ||
      event.type === 'consensus_reached' ||
      event.type === 'debate_started' ||
      event.type === 'debate_completed'
    ) {
      this.postMessage(event);
    }
  }

  private async exportDebate(format: 'json' | 'markdown' | 'html'): Promise<void> {
    if (!this.debate) return;

    let content: string;
    let language: string;

    switch (format) {
      case 'json':
        content = JSON.stringify(this.debate, null, 2);
        language = 'json';
        break;

      case 'markdown':
        content = this.generateMarkdownExport();
        language = 'markdown';
        break;

      case 'html':
        content = this.generateHtmlExport();
        language = 'html';
        break;
    }

    const doc = await vscode.workspace.openTextDocument({ content, language });
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside });
  }

  private generateMarkdownExport(): string {
    if (!this.debate) return '';

    const lines = [
      `# Debate: ${this.debate.question}`,
      '',
      `**Status:** ${this.debate.status}`,
      `**Rounds:** ${this.debate.currentRound}/${this.debate.totalRounds}`,
      `**Started:** ${new Date(this.debate.startTime).toISOString()}`,
      this.debate.endTime ? `**Ended:** ${new Date(this.debate.endTime).toISOString()}` : '',
      '',
      '## Discussion',
      '',
    ];

    let currentRound = 0;
    for (const message of this.debate.messages) {
      if (message.round !== currentRound) {
        currentRound = message.round;
        lines.push(`### Round ${currentRound}`, '');
      }

      lines.push(`**${message.agent.name}** (${message.agent.provider}):`, '', message.content, '');
    }

    if (this.debate.consensus) {
      lines.push(
        '## Consensus',
        '',
        `**Method:** ${this.debate.consensus.method}`,
        `**Confidence:** ${(this.debate.consensus.confidence * 100).toFixed(1)}%`,
        '',
        this.debate.consensus.answer,
      );
    }

    return lines.join('\n');
  }

  private generateHtmlExport(): string {
    // Simple HTML export - the webview could also export its rendered HTML
    return `<!DOCTYPE html>
<html>
<head>
  <title>Debate: ${this.debate?.question || 'Unknown'}</title>
  <style>
    body { font-family: system-ui; max-width: 800px; margin: 0 auto; padding: 20px; }
    .message { margin: 10px 0; padding: 15px; border-radius: 8px; background: #f5f5f5; }
    .consensus { background: #e8f5e9; border: 2px solid #4caf50; }
    h1 { color: #333; }
    h2 { color: #666; border-bottom: 1px solid #ddd; }
  </style>
</head>
<body>
  <h1>${this.debate?.question || 'Debate'}</h1>
  ${
    this.debate?.messages
      .map(
        (m) => `
    <div class="message">
      <strong>${m.agent.name}</strong>
      <p>${m.content}</p>
    </div>
  `,
      )
      .join('') || ''
  }
  ${
    this.debate?.consensus
      ? `
    <div class="message consensus">
      <h2>Consensus</h2>
      <p>${this.debate.consensus.answer}</p>
      <p><em>Confidence: ${(this.debate.consensus.confidence * 100).toFixed(1)}%</em></p>
    </div>
  `
      : ''
  }
</body>
</html>`;
  }

  private async sendFeedback(vote: 'up' | 'down', comment?: string): Promise<void> {
    if (!this.debate) return;

    const config = vscode.workspace.getConfiguration('aragora');
    const apiUrl = config.get<string>('apiUrl') || 'https://api.aragora.ai';
    const apiKey = config.get<string>('apiKey') || '';

    try {
      const response = await fetch(`${apiUrl}/api/v1/debates/${this.debate.id}/feedback`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey && { Authorization: `Bearer ${apiKey}` }),
        },
        body: JSON.stringify({ vote, comment }),
      });

      if (response.ok) {
        vscode.window.showInformationMessage('Thank you for your feedback!');
      }
    } catch (error) {
      logger.error('Failed to send feedback:', error);
    }
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
  <title>Aragora Debate</title>
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    window.vscodeApi = vscode;
    window.initialView = 'debate';
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
    DebatePanel.currentPanel = undefined;
    this.panel.dispose();
    this.disposables.forEach((d) => d.dispose());
  }
}

/**
 * Register debate panel commands
 */
export function registerDebatePanelCommands(
  context: vscode.ExtensionContext,
  streamManager?: StreamManager,
): void {
  // Show debate panel
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.showDebatePanel', () => {
      DebatePanel.createOrShow(context.extensionUri, streamManager);
    }),
  );

  // Clear debate context
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.clearDebateContext', async () => {
      await context.workspaceState.update('debateContext', []);
      vscode.window.showInformationMessage('Debate context cleared');
    }),
  );

  // View debate context
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.viewDebateContext', async () => {
      const existingContext = context.workspaceState.get<string[]>('debateContext', []);

      if (existingContext.length === 0) {
        vscode.window.showInformationMessage('No code snippets in debate context');
        return;
      }

      const content = existingContext.join('\n\n---\n');
      const doc = await vscode.workspace.openTextDocument({
        content: `# Debate Context\n\n${content}`,
        language: 'markdown',
      });
      await vscode.window.showTextDocument(doc);
    }),
  );
}
