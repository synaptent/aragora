/**
 * Aragora Debate Viewer Panel
 *
 * Live debate viewer for real-time streaming of deliberations from the
 * Control Plane. Displays active debates, round progress, agent messages,
 * and SLA status.
 */

import * as vscode from 'vscode';
import {
  ControlPlaneService,
  Deliberation,
  ControlPlaneEvent,
  getControlPlaneService,
} from '../services/ControlPlaneService';

interface AgentMessage {
  agent: string;
  content: string;
  round: number;
  timestamp: number;
}

interface DebateViewerState {
  deliberationId: string | null;
  deliberation: Deliberation | null;
  messages: AgentMessage[];
  slaWarnings: string[];
  connectionStatus: 'connected' | 'disconnected' | 'connecting';
}

/**
 * Panel for viewing live debates from the Control Plane
 */
export class DebateViewerPanel {
  public static currentPanel: DebateViewerPanel | undefined;
  public static readonly viewType = 'aragora.debateViewerPanel';

  private readonly panel: vscode.WebviewPanel;
  private readonly extensionUri: vscode.Uri;
  private disposables: vscode.Disposable[] = [];
  private controlPlaneService: ControlPlaneService;
  private deliberationSubscription: vscode.Disposable | null = null;

  private state: DebateViewerState = {
    deliberationId: null,
    deliberation: null,
    messages: [],
    slaWarnings: [],
    connectionStatus: 'disconnected',
  };

  private constructor(
    panel: vscode.WebviewPanel,
    extensionUri: vscode.Uri,
    controlPlaneService?: ControlPlaneService,
  ) {
    this.panel = panel;
    this.extensionUri = extensionUri;
    this.controlPlaneService = controlPlaneService || getControlPlaneService();

    // Set webview content
    this.panel.webview.html = this.getHtmlContent();

    // Handle panel disposal
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

    // Handle messages from webview
    this.panel.webview.onDidReceiveMessage(
      (message) => this.handleWebviewMessage(message),
      null,
      this.disposables,
    );

    // Subscribe to control plane events
    this.disposables.push(
      this.controlPlaneService.subscribe((event) => this.handleControlPlaneEvent(event)),
    );

    // Update connection status
    this.state.connectionStatus = this.controlPlaneService.getConnectionStatus();
    this.postMessage({ type: 'state_update', state: this.state });
  }

  /**
   * Create or show the debate viewer panel
   */
  public static createOrShow(
    extensionUri: vscode.Uri,
    controlPlaneService?: ControlPlaneService,
  ): DebateViewerPanel {
    const column = vscode.ViewColumn.Beside;

    // If we already have a panel, show it
    if (DebateViewerPanel.currentPanel) {
      DebateViewerPanel.currentPanel.panel.reveal(column);
      return DebateViewerPanel.currentPanel;
    }

    // Create a new panel
    const panel = vscode.window.createWebviewPanel(
      DebateViewerPanel.viewType,
      'Live Debate Viewer',
      column,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'webview-ui', 'dist')],
      },
    );

    DebateViewerPanel.currentPanel = new DebateViewerPanel(
      panel,
      extensionUri,
      controlPlaneService,
    );
    return DebateViewerPanel.currentPanel;
  }

  /**
   * Connect to a specific deliberation for live streaming
   */
  public async connect(deliberationId: string): Promise<void> {
    // Clean up previous subscription
    if (this.deliberationSubscription) {
      this.deliberationSubscription.dispose();
    }

    this.state.deliberationId = deliberationId;
    this.state.messages = [];
    this.state.slaWarnings = [];

    // Ensure connected to control plane
    if (this.controlPlaneService.getConnectionStatus() !== 'connected') {
      await this.controlPlaneService.connect();
    }

    // Subscribe to this deliberation
    this.deliberationSubscription = this.controlPlaneService.connectToDeliberation(deliberationId);
    this.disposables.push(this.deliberationSubscription);

    // Fetch current state
    const deliberations = await this.controlPlaneService.getActiveDeliberations();
    this.state.deliberation = deliberations.find((d) => d.id === deliberationId) || null;

    // Update panel title
    if (this.state.deliberation) {
      this.panel.title = `Debate: ${this.state.deliberation.question.substring(0, 30)}...`;
    }

    this.postMessage({ type: 'state_update', state: this.state });
  }

  /**
   * Disconnect from the current deliberation
   */
  public disconnect(): void {
    if (this.deliberationSubscription) {
      this.deliberationSubscription.dispose();
      this.deliberationSubscription = null;
    }

    this.state.deliberationId = null;
    this.state.deliberation = null;
    this.state.messages = [];
    this.state.slaWarnings = [];

    this.panel.title = 'Live Debate Viewer';
    this.postMessage({ type: 'state_update', state: this.state });
  }

  private handleControlPlaneEvent(event: ControlPlaneEvent): void {
    // Filter for relevant deliberation events
    const eventDebateId = event.data.deliberation_id as string | undefined;
    if (eventDebateId && eventDebateId !== this.state.deliberationId) {
      return;
    }

    switch (event.type) {
      case 'connection_status':
        this.state.connectionStatus = event.data.status as 'connected' | 'disconnected';
        break;

      case 'deliberation_started':
        this.state.deliberation = {
          id: event.data.deliberation_id as string,
          question: event.data.question as string,
          status: 'running',
          currentRound: 0,
          totalRounds: event.data.total_rounds as number,
          agents: event.data.agents as string[],
          startTime: event.timestamp,
        };
        break;

      case 'deliberation_progress':
        this.state.messages.push({
          agent: event.data.agent as string,
          content: event.data.content as string,
          round: event.data.round as number,
          timestamp: event.timestamp,
        });
        break;

      case 'deliberation_round':
        if (this.state.deliberation) {
          this.state.deliberation.currentRound = event.data.round as number;
        }
        break;

      case 'deliberation_vote':
        this.state.messages.push({
          agent: event.data.agent as string,
          content: `Vote: ${event.data.choice} (confidence: ${((event.data.confidence as number) * 100).toFixed(0)}%)`,
          round: this.state.deliberation?.currentRound || 0,
          timestamp: event.timestamp,
        });
        break;

      case 'deliberation_consensus':
        if (this.state.deliberation) {
          this.state.deliberation.status = 'completed';
          this.state.deliberation.consensusReached = event.data.consensus_reached as boolean;
          this.state.deliberation.confidence = event.data.confidence as number;
          this.state.deliberation.endTime = event.timestamp;
        }
        break;

      case 'deliberation_completed':
        if (this.state.deliberation) {
          this.state.deliberation.status = 'completed';
          this.state.deliberation.endTime = event.timestamp;
        }
        break;

      case 'deliberation_failed':
        if (this.state.deliberation) {
          this.state.deliberation.status = 'failed';
          this.state.deliberation.endTime = event.timestamp;
        }
        break;

      case 'deliberation_sla_warning':
        this.state.slaWarnings.push(
          `SLA Warning: ${event.data.elapsed_seconds}s / ${event.data.timeout_seconds}s`,
        );
        break;
    }

    this.postMessage({ type: 'state_update', state: this.state });
    this.postMessage({ type: 'event', event });
  }

  private async handleWebviewMessage(message: Record<string, unknown>): Promise<void> {
    switch (message.type) {
      case 'ready':
        this.postMessage({ type: 'state_update', state: this.state });
        break;

      case 'connect':
        await this.controlPlaneService.connect();
        break;

      case 'disconnect':
        this.disconnect();
        break;

      case 'connect_deliberation':
        await this.connect(message.deliberation_id as string);
        break;

      case 'trigger_deliberation': {
        const id = await this.controlPlaneService.triggerDeliberation(
          message.question as string,
          message.agents as string[] | undefined,
          message.rounds as number | undefined,
        );
        if (id) {
          await this.connect(id);
        }
        break;
      }

      case 'list_deliberations': {
        const deliberations = await this.controlPlaneService.getActiveDeliberations();
        this.postMessage({ type: 'deliberations_list', deliberations });
        break;
      }

      case 'copy_result':
        if (this.state.deliberation) {
          const text = this.state.messages.map((m) => `${m.agent}: ${m.content}`).join('\n\n');
          await vscode.env.clipboard.writeText(text);
          vscode.window.showInformationMessage('Debate content copied to clipboard');
        }
        break;
    }
  }

  private postMessage(message: Record<string, unknown>): void {
    this.panel.webview.postMessage(message);
  }

  private getHtmlContent(): string {
    const webview = this.panel.webview;
    const nonce = this.getNonce();

    // Inline styles for the viewer
    const styles = `
      body {
        font-family: var(--vscode-font-family);
        font-size: var(--vscode-font-size);
        color: var(--vscode-foreground);
        background: var(--vscode-editor-background);
        padding: 12px;
        margin: 0;
      }
      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--vscode-panel-border);
      }
      .status {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .status-indicator {
        width: 8px;
        height: 8px;
        border-radius: 50%;
      }
      .status-indicator.connected { background: #4caf50; }
      .status-indicator.disconnected { background: #f44336; }
      .status-indicator.connecting { background: #ff9800; animation: pulse 1s infinite; }
      @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
      .question {
        font-size: 1.2em;
        font-weight: 600;
        margin-bottom: 8px;
      }
      .progress {
        display: flex;
        gap: 12px;
        margin-bottom: 16px;
        font-size: 0.9em;
        color: var(--vscode-descriptionForeground);
      }
      .messages {
        max-height: 60vh;
        overflow-y: auto;
        border: 1px solid var(--vscode-panel-border);
        border-radius: 4px;
        padding: 8px;
      }
      .message {
        margin-bottom: 12px;
        padding: 8px 12px;
        border-radius: 4px;
        background: var(--vscode-editor-inactiveSelectionBackground);
      }
      .message-header {
        display: flex;
        justify-content: space-between;
        margin-bottom: 4px;
        font-weight: 600;
      }
      .agent-name { color: var(--vscode-textLink-foreground); }
      .round-badge {
        font-size: 0.75em;
        padding: 2px 6px;
        border-radius: 10px;
        background: var(--vscode-badge-background);
        color: var(--vscode-badge-foreground);
      }
      .message-content {
        white-space: pre-wrap;
        word-break: break-word;
      }
      .sla-warning {
        padding: 8px;
        margin-bottom: 8px;
        border-radius: 4px;
        background: var(--vscode-inputValidation-warningBackground);
        border: 1px solid var(--vscode-inputValidation-warningBorder);
        color: var(--vscode-inputValidation-warningForeground);
      }
      .consensus {
        margin-top: 16px;
        padding: 12px;
        border-radius: 4px;
        background: var(--vscode-inputValidation-infoBackground);
        border: 1px solid var(--vscode-inputValidation-infoBorder);
      }
      .actions {
        display: flex;
        gap: 8px;
        margin-top: 12px;
      }
      button {
        padding: 6px 12px;
        border: none;
        border-radius: 4px;
        background: var(--vscode-button-background);
        color: var(--vscode-button-foreground);
        cursor: pointer;
      }
      button:hover { background: var(--vscode-button-hoverBackground); }
      button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .empty-state {
        text-align: center;
        padding: 40px;
        color: var(--vscode-descriptionForeground);
      }
      input {
        width: 100%;
        padding: 6px 8px;
        margin-bottom: 8px;
        border: 1px solid var(--vscode-input-border);
        background: var(--vscode-input-background);
        color: var(--vscode-input-foreground);
        border-radius: 4px;
      }
    `;

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <title>Live Debate Viewer</title>
  <style>${styles}</style>
</head>
<body>
  <div id="root">
    <div class="header">
      <h2>Live Debate Viewer</h2>
      <div class="status">
        <div class="status-indicator disconnected" id="status-indicator"></div>
        <span id="status-text">Disconnected</span>
      </div>
    </div>

    <div id="content">
      <div class="empty-state">
        <p>No active debate selected.</p>
        <div class="actions" style="justify-content: center; margin-top: 16px;">
          <button onclick="connect()">Connect to Control Plane</button>
          <button onclick="listDeliberations()">List Active Debates</button>
        </div>
        <div style="margin-top: 20px;">
          <input type="text" id="question-input" placeholder="Enter a question to debate...">
          <button onclick="triggerDebate()">Start New Debate</button>
        </div>
      </div>
    </div>

    <div id="deliberations-modal" style="display: none;">
      <h3>Active Deliberations</h3>
      <div id="deliberations-list"></div>
    </div>
  </div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    let state = {
      deliberationId: null,
      deliberation: null,
      messages: [],
      slaWarnings: [],
      connectionStatus: 'disconnected'
    };

    // Message handlers
    window.addEventListener('message', (event) => {
      const message = event.data;
      switch (message.type) {
        case 'state_update':
          state = message.state;
          render();
          break;
        case 'deliberations_list':
          showDeliberationsList(message.deliberations);
          break;
        case 'event':
          // Optional: handle individual events for animations
          break;
      }
    });

    function render() {
      // Update status indicator
      const indicator = document.getElementById('status-indicator');
      const statusText = document.getElementById('status-text');
      indicator.className = 'status-indicator ' + state.connectionStatus;
      statusText.textContent = state.connectionStatus.charAt(0).toUpperCase() + state.connectionStatus.slice(1);

      const content = document.getElementById('content');

      if (!state.deliberation) {
        content.innerHTML = \`
          <div class="empty-state">
            <p>No active debate selected.</p>
            <div class="actions" style="justify-content: center; margin-top: 16px;">
              <button onclick="connect()">Connect to Control Plane</button>
              <button onclick="listDeliberations()">List Active Debates</button>
            </div>
            <div style="margin-top: 20px;">
              <input type="text" id="question-input" placeholder="Enter a question to debate...">
              <button onclick="triggerDebate()">Start New Debate</button>
            </div>
          </div>
        \`;
        return;
      }

      const d = state.deliberation;
      const duration = d.endTime
        ? ((d.endTime - d.startTime) / 1000).toFixed(1) + 's'
        : ((Date.now() - d.startTime) / 1000).toFixed(0) + 's...';

      let html = \`
        <div class="question">\${escapeHtml(d.question)}</div>
        <div class="progress">
          <span>Round \${d.currentRound} / \${d.totalRounds}</span>
          <span>Status: \${d.status}</span>
          <span>Duration: \${duration}</span>
          \${d.confidence ? \`<span>Confidence: \${(d.confidence * 100).toFixed(0)}%</span>\` : ''}
        </div>
      \`;

      // SLA warnings
      if (state.slaWarnings.length > 0) {
        html += state.slaWarnings.map(w => \`<div class="sla-warning">\${escapeHtml(w)}</div>\`).join('');
      }

      // Messages
      html += '<div class="messages">';
      for (const msg of state.messages) {
        html += \`
          <div class="message">
            <div class="message-header">
              <span class="agent-name">\${escapeHtml(msg.agent)}</span>
              <span class="round-badge">Round \${msg.round}</span>
            </div>
            <div class="message-content">\${escapeHtml(msg.content)}</div>
          </div>
        \`;
      }
      html += '</div>';

      // Consensus
      if (d.status === 'completed' && d.consensusReached) {
        html += \`
          <div class="consensus">
            <strong>Consensus Reached</strong>
            <p>Confidence: \${((d.confidence || 0) * 100).toFixed(0)}%</p>
          </div>
        \`;
      }

      // Actions
      html += \`
        <div class="actions">
          <button onclick="copyResult()">Copy Content</button>
          <button onclick="disconnect()">Disconnect</button>
          <button onclick="listDeliberations()">Switch Session</button>
        </div>
      \`;

      content.innerHTML = html;
    }

    function showDeliberationsList(deliberations) {
      const modal = document.getElementById('deliberations-modal');
      const list = document.getElementById('deliberations-list');

      if (deliberations.length === 0) {
        list.innerHTML = '<p>No active vetted decisionmaking sessions.</p>';
      } else {
        list.innerHTML = deliberations.map(d => \`
          <div style="margin-bottom: 8px; padding: 8px; border: 1px solid var(--vscode-panel-border); border-radius: 4px; cursor: pointer;"
               onclick="connectDeliberation('\${d.id}')">
            <strong>\${escapeHtml(d.question.substring(0, 50))}...</strong>
            <div style="font-size: 0.9em; color: var(--vscode-descriptionForeground);">
              Status: \${d.status} | Round \${d.currentRound}/\${d.totalRounds}
            </div>
          </div>
        \`).join('');
      }

      modal.style.display = 'block';
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    function connect() {
      vscode.postMessage({ type: 'connect' });
    }

    function disconnect() {
      vscode.postMessage({ type: 'disconnect' });
    }

    function listDeliberations() {
      vscode.postMessage({ type: 'list_deliberations' });
    }

    function connectDeliberation(id) {
      document.getElementById('deliberations-modal').style.display = 'none';
      vscode.postMessage({ type: 'connect_deliberation', deliberation_id: id });
    }

    function triggerDebate() {
      const input = document.getElementById('question-input');
      const question = input ? input.value.trim() : '';
      if (question) {
        vscode.postMessage({
          type: 'trigger_deliberation',
          question: question,
          agents: ['claude', 'gpt-4'],
          rounds: 3
        });
      }
    }

    function copyResult() {
      vscode.postMessage({ type: 'copy_result' });
    }

    // Initial ready message
    vscode.postMessage({ type: 'ready' });
  </script>
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
    DebateViewerPanel.currentPanel = undefined;

    if (this.deliberationSubscription) {
      this.deliberationSubscription.dispose();
    }

    this.panel.dispose();
    this.disposables.forEach((d) => d.dispose());
  }
}

/**
 * Register debate viewer commands
 */
export function registerDebateViewerCommands(
  context: vscode.ExtensionContext,
  controlPlaneService?: ControlPlaneService,
): void {
  // Show debate viewer panel
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.showDebateViewer', () => {
      DebateViewerPanel.createOrShow(context.extensionUri, controlPlaneService);
    }),
  );

  // Connect to specific deliberation
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.connectToDeliberation', async () => {
      const deliberationId = await vscode.window.showInputBox({
        prompt: 'Enter vetted decisionmaking session ID',
        placeHolder: 'decisionmaking-id',
      });

      if (deliberationId) {
        const panel = DebateViewerPanel.createOrShow(context.extensionUri, controlPlaneService);
        await panel.connect(deliberationId);
      }
    }),
  );

  // Trigger a new deliberation from editor selection
  context.subscriptions.push(
    vscode.commands.registerCommand('aragora.triggerDeliberation', async () => {
      const editor = vscode.window.activeTextEditor;
      let question = '';

      // Use selected text or prompt for question
      if (editor && !editor.selection.isEmpty) {
        question = editor.document.getText(editor.selection);
      } else {
        const input = await vscode.window.showInputBox({
          prompt: 'Enter the question for vetted decisionmaking',
          placeHolder: 'What is the best approach for...',
        });
        question = input || '';
      }

      if (question) {
        const service = controlPlaneService || getControlPlaneService();
        const deliberationId = await service.triggerDeliberation(question);

        if (deliberationId) {
          const panel = DebateViewerPanel.createOrShow(context.extensionUri, service);
          await panel.connect(deliberationId);
        }
      }
    }),
  );
}
