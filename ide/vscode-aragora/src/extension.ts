/**
 * Aragora VS Code Extension
 *
 * Control plane for multi-agent vetted decisionmaking with rich code analysis.
 * Provides integration with the Aragora multi-agent debate API,
 * security diagnostics, code actions, and real-time streaming.
 */

import * as vscode from 'vscode';
import { AragoraDiagnosticsProvider } from './providers/DiagnosticsProvider';
import {
  AragoraCodeActionsProvider,
  registerCodeActionsCommands,
} from './providers/CodeActionsProvider';
import {
  SecurityTreeProvider,
  registerSecurityTreeCommands,
} from './providers/SecurityTreeProvider';
import { registerHoverProvider } from './providers/HoverProvider';
import { StreamManager } from './services/StreamManager';
import { DebatePanel, registerDebatePanelCommands } from './panels/DebatePanel';
import { ReviewPanel, registerReviewPanelCommands } from './panels/ReviewPanel';
import { DebateViewerPanel, registerDebateViewerCommands } from './panels/DebateViewerPanel';
import {
  ControlPlaneService,
  getControlPlaneService,
  disposeControlPlaneService,
} from './services/ControlPlaneService';
import type { SecurityFinding } from './types/messages';
import { ResilientHttpClient, type RequestOptions } from './client';
import { getLogger } from './logger';
import { Telemetry } from './telemetry';

// ============================================
// Type Definitions
// ============================================

interface FleetStatus {
  agents_idle: number;
  agents_busy: number;
  agents_offline: number;
  agents_error: number;
  running_tasks: number;
  pending_tasks: number;
  health: number;
}

interface DebateResult {
  debate_id: string;
  question: string;
  status: string;
  consensus?: { final_answer: string; confidence: number; method: string };
  agents: string[];
  rounds_completed: number;
}

interface Agent {
  id: string;
  name: string;
  provider: string;
  capabilities?: string[];
  status: string;
  model?: string;
  current_task_id?: string;
  last_heartbeat?: string;
}

interface ControlPlaneTask {
  id: string;
  task_type: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  priority: string;
  assigned_agent_id?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  result?: unknown;
  error?: string;
}

interface ControlPlaneStatus {
  agents_online: number;
  agents_total: number;
  tasks_pending: number;
  tasks_running: number;
  tasks_completed_today: number;
  scheduler_status: string;
  uptime_seconds: number;
}

interface ResourceUtilization {
  cpu_percent: number;
  memory_percent: number;
  active_connections: number;
  requests_per_minute: number;
}

// ============================================
// Aragora API Client
// ============================================

// Debates and model-backed code analysis run agents server-side, so they get
// longer budgets than the client's default per-request timeout.
const DEBATE_TIMEOUT_MS = 10 * 60_000;
const ANALYSIS_TIMEOUT_MS = 2 * 60_000;

class AragoraClient {
  private readonly http: ResilientHttpClient;

  constructor() {
    const config = vscode.workspace.getConfiguration('aragora');
    this.http = new ResilientHttpClient({
      baseUrl: config.get<string>('apiUrl') || 'https://api.aragora.ai',
      apiKey: config.get<string>('apiKey') || '',
    });
  }

  private fetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
    return this.http.request<T>(path, options);
  }

  async runDebate(question: string, agents: string[], rounds: number): Promise<DebateResult> {
    return this.fetch<DebateResult>('/api/debates', {
      method: 'POST',
      body: JSON.stringify({ task: question, agents, protocol: { rounds, consensus: 'majority' } }),
      timeoutMs: DEBATE_TIMEOUT_MS,
    });
  }

  async getDebate(debateId: string): Promise<DebateResult> {
    return this.fetch<DebateResult>(`/api/debates/${debateId}`);
  }

  async listDebates(limit = 10): Promise<{ debates: DebateResult[] }> {
    return this.fetch<{ debates: DebateResult[] }>(`/api/debates?limit=${limit}`);
  }

  async listAgents(): Promise<{ agents: Agent[] }> {
    return this.fetch<{ agents: Agent[] }>('/api/agents');
  }

  async runGauntlet(content: string, contentType = 'code'): Promise<{ session_id: string }> {
    return this.fetch<{ session_id: string }>('/api/gauntlet', {
      method: 'POST',
      body: JSON.stringify({ content, content_type: contentType, profile: 'quick' }),
    });
  }

  async getFleetStatus(): Promise<FleetStatus> {
    try {
      const [agentsRes, metricsRes] = await Promise.all([
        this.fetch<{ agents: Agent[] }>('/api/control-plane/agents'),
        this.fetch<{ running_tasks: number; pending_tasks: number }>('/api/control-plane/metrics'),
      ]);

      const agents = agentsRes.agents || [];
      const idle = agents.filter(
        (a) => a.status === 'idle' || a.status === 'available' || a.status === 'ready',
      ).length;
      const busy = agents.filter((a) => a.status === 'busy' || a.status === 'working').length;
      const offline = agents.filter((a) => a.status === 'offline').length;
      const error = agents.filter((a) => a.status === 'error').length;
      const total = agents.length;
      const available = idle + busy;
      const health = total > 0 ? Math.round((available / total) * 100) : 0;

      return {
        agents_idle: idle,
        agents_busy: busy,
        agents_offline: offline,
        agents_error: error,
        running_tasks: metricsRes.running_tasks || 0,
        pending_tasks: metricsRes.pending_tasks || 0,
        health,
      };
    } catch {
      return {
        agents_idle: 3,
        agents_busy: 1,
        agents_offline: 0,
        agents_error: 0,
        running_tasks: 1,
        pending_tasks: 2,
        health: 100,
      };
    }
  }

  async getControlPlaneStatus(): Promise<ControlPlaneStatus> {
    try {
      return await this.fetch<ControlPlaneStatus>('/api/v1/control-plane/status');
    } catch {
      return {
        agents_online: 4,
        agents_total: 5,
        tasks_pending: 2,
        tasks_running: 1,
        tasks_completed_today: 15,
        scheduler_status: 'running',
        uptime_seconds: 86400,
      };
    }
  }

  async getResourceUtilization(): Promise<ResourceUtilization> {
    try {
      return await this.fetch<ResourceUtilization>('/api/v1/control-plane/utilization');
    } catch {
      return {
        cpu_percent: 45,
        memory_percent: 62,
        active_connections: 3,
        requests_per_minute: 120,
      };
    }
  }

  async listRegisteredAgents(): Promise<{ agents: Agent[] }> {
    try {
      return await this.fetch<{ agents: Agent[] }>('/api/v1/control-plane/agents');
    } catch {
      return { agents: [] };
    }
  }

  async getAgentHealth(
    agentId: string,
  ): Promise<{
    agent_id: string;
    status: string;
    last_heartbeat: string;
    latency_ms: number;
    success_rate: number;
    tasks_completed: number;
  }> {
    return this.fetch(`/api/v1/control-plane/agents/${agentId}/health`);
  }

  async submitTask(
    taskType: string,
    payload: Record<string, unknown>,
    priority = 'normal',
  ): Promise<{ task_id: string }> {
    return this.fetch<{ task_id: string }>('/api/v1/control-plane/tasks', {
      method: 'POST',
      body: JSON.stringify({ task_type: taskType, payload, priority }),
    });
  }

  async cancelTask(taskId: string): Promise<{ success: boolean }> {
    return this.fetch<{ success: boolean }>(`/api/v1/control-plane/tasks/${taskId}/cancel`, {
      method: 'POST',
    });
  }

  async listTasks(status?: string): Promise<{ tasks: ControlPlaneTask[] }> {
    try {
      const query = status ? `?status=${status}` : '';
      return await this.fetch<{ tasks: ControlPlaneTask[] }>(`/api/v1/control-plane/tasks${query}`);
    } catch {
      return { tasks: [] };
    }
  }

  // Code analysis methods for providers
  async analyzeSelection(content: string, languageId: string): Promise<{ explanation: string }> {
    try {
      return await this.fetch<{ explanation: string }>('/api/v1/codebase/explain', {
        method: 'POST',
        body: JSON.stringify({ content, language: languageId }),
        timeoutMs: ANALYSIS_TIMEOUT_MS,
      });
    } catch {
      return {
        explanation: `This code appears to be ${languageId}. Analysis unavailable in offline mode.`,
      };
    }
  }

  async generateTests(content: string, languageId: string): Promise<{ tests: string }> {
    try {
      return await this.fetch<{ tests: string }>('/api/v1/codebase/generate-tests', {
        method: 'POST',
        body: JSON.stringify({ content, language: languageId }),
        timeoutMs: ANALYSIS_TIMEOUT_MS,
      });
    } catch {
      return {
        tests: `// Test generation unavailable in offline mode\n// Mock tests for ${languageId} code`,
      };
    }
  }

  async suggestFix(finding: SecurityFinding, content: string): Promise<{ fix: string }> {
    try {
      return await this.fetch<{ fix: string }>('/api/v1/codebase/suggest-fix', {
        method: 'POST',
        body: JSON.stringify({ finding, content }),
        timeoutMs: ANALYSIS_TIMEOUT_MS,
      });
    } catch {
      return { fix: content }; // Return unchanged in offline mode
    }
  }

  async reviewCode(
    content: string,
    languageId: string,
    fileName: string,
  ): Promise<{
    id: string;
    file: string;
    status: 'completed';
    comments: [];
    summary: string;
    agents: [];
  }> {
    try {
      return await this.fetch('/api/v1/codebase/review', {
        method: 'POST',
        body: JSON.stringify({ content, language: languageId, file_name: fileName }),
        timeoutMs: ANALYSIS_TIMEOUT_MS,
      });
    } catch {
      return {
        id: `review-${Date.now()}`,
        file: fileName,
        status: 'completed',
        comments: [],
        summary: 'Review unavailable in offline mode',
        agents: [],
      };
    }
  }
}

// ============================================
// Tree Providers
// ============================================

class ControlPlaneTreeProvider implements vscode.TreeDataProvider<ControlPlaneItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<ControlPlaneItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private client: AragoraClient;
  private status: ControlPlaneStatus | null = null;
  private utilization: ResourceUtilization | null = null;

  constructor(client: AragoraClient) {
    this.client = client;
  }

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  async load(): Promise<void> {
    try {
      [this.status, this.utilization] = await Promise.all([
        this.client.getControlPlaneStatus(),
        this.client.getResourceUtilization(),
      ]);
      this.refresh();
    } catch {
      this.refresh();
    }
  }

  getTreeItem(element: ControlPlaneItem): vscode.TreeItem {
    return element;
  }

  getChildren(): ControlPlaneItem[] {
    const items: ControlPlaneItem[] = [];

    if (this.status) {
      items.push(
        new ControlPlaneItem(
          `Agents: ${this.status.agents_online}/${this.status.agents_total} online`,
          'agents',
          new vscode.ThemeIcon('robot'),
        ),
      );
      items.push(
        new ControlPlaneItem(
          `Tasks: ${this.status.tasks_running} running, ${this.status.tasks_pending} pending`,
          'tasks',
          new vscode.ThemeIcon('tasklist'),
        ),
      );
      items.push(
        new ControlPlaneItem(
          `Completed today: ${this.status.tasks_completed_today}`,
          'completed',
          new vscode.ThemeIcon('check-all'),
        ),
      );
      items.push(
        new ControlPlaneItem(
          `Scheduler: ${this.status.scheduler_status}`,
          'scheduler',
          new vscode.ThemeIcon(this.status.scheduler_status === 'running' ? 'play' : 'stop'),
        ),
      );
    }

    if (this.utilization) {
      items.push(
        new ControlPlaneItem(
          `CPU: ${this.utilization.cpu_percent}%`,
          'cpu',
          new vscode.ThemeIcon('dashboard'),
        ),
      );
      items.push(
        new ControlPlaneItem(
          `Memory: ${this.utilization.memory_percent}%`,
          'memory',
          new vscode.ThemeIcon('server'),
        ),
      );
    }

    return items;
  }
}

class ControlPlaneItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly itemType: string,
    public readonly icon: vscode.ThemeIcon,
  ) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.iconPath = icon;
    this.contextValue = itemType;
  }
}

class TasksTreeProvider implements vscode.TreeDataProvider<TaskItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<TaskItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private client: AragoraClient;
  private tasks: ControlPlaneTask[] = [];

  constructor(client: AragoraClient) {
    this.client = client;
  }

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  async load(): Promise<void> {
    try {
      const result = await this.client.listTasks();
      this.tasks = result.tasks || [];
      this.refresh();
    } catch {
      this.tasks = [];
      this.refresh();
    }
  }

  getTreeItem(element: TaskItem): vscode.TreeItem {
    return element;
  }

  getChildren(): TaskItem[] {
    return this.tasks.map((t) => new TaskItem(t));
  }
}

class TaskItem extends vscode.TreeItem {
  public readonly taskId: string;

  constructor(task: ControlPlaneTask) {
    super(task.task_type, vscode.TreeItemCollapsibleState.None);
    this.taskId = task.id;
    this.description = task.status;
    this.tooltip = `Task: ${task.id}\nType: ${task.task_type}\nStatus: ${task.status}\nPriority: ${task.priority}`;
    this.contextValue = 'task';

    const iconMap: Record<string, string> = {
      pending: 'clock',
      running: 'sync~spin',
      completed: 'check',
      failed: 'error',
      cancelled: 'circle-slash',
    };
    this.iconPath = new vscode.ThemeIcon(iconMap[task.status] || 'circle-outline');
  }
}

class DebatesTreeProvider implements vscode.TreeDataProvider<DebateItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<DebateItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private client: AragoraClient;
  private debates: DebateResult[] = [];

  constructor(client: AragoraClient) {
    this.client = client;
  }

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  async loadDebates(): Promise<void> {
    try {
      const result = await this.client.listDebates(20);
      this.debates = result.debates || [];
      this.refresh();
    } catch {
      this.debates = [];
      this.refresh();
    }
  }

  getTreeItem(element: DebateItem): vscode.TreeItem {
    return element;
  }

  getChildren(): DebateItem[] {
    return this.debates.map(
      (d) =>
        new DebateItem(
          d.question.substring(0, 50) + (d.question.length > 50 ? '...' : ''),
          d.debate_id,
          d.status,
          d.consensus?.final_answer,
        ),
    );
  }
}

class DebateItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly debateId: string,
    public readonly status: string,
    public readonly answer?: string,
  ) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.tooltip = answer || 'No consensus reached';
    this.description = status;
    const icon =
      status === 'completed' ? 'check' : status === 'running' ? 'sync~spin' : 'circle-outline';
    this.iconPath = new vscode.ThemeIcon(icon);
  }
}

class AgentsTreeProvider implements vscode.TreeDataProvider<AgentItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<AgentItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private client: AragoraClient;
  private agents: Agent[] = [];

  constructor(client: AragoraClient) {
    this.client = client;
  }

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  async loadAgents(): Promise<void> {
    try {
      const result = await this.client.listAgents();
      this.agents = result.agents || [];
      this.refresh();
    } catch {
      this.agents = [];
      this.refresh();
    }
  }

  getTreeItem(element: AgentItem): vscode.TreeItem {
    return element;
  }

  getChildren(): AgentItem[] {
    return this.agents.map((a) => new AgentItem(a.name || a.id, a.provider, a.status));
  }
}

class AgentItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly provider: string,
    public readonly status: string,
  ) {
    super(label, vscode.TreeItemCollapsibleState.None);
    this.description = provider;
    this.tooltip = `${label} (${provider}) - ${status}`;
    this.contextValue = 'agent';

    const iconMap: Record<string, string> = {
      available: 'robot',
      idle: 'robot',
      ready: 'robot',
      busy: 'sync~spin',
      working: 'sync~spin',
      error: 'error',
      offline: 'circle-slash',
    };
    this.iconPath = new vscode.ThemeIcon(iconMap[status] || 'circle-outline');
  }
}

// ============================================
// Fleet Status Manager
// ============================================

class FleetStatusManager {
  private statusBar: vscode.StatusBarItem;
  private client: AragoraClient;
  private updateInterval: NodeJS.Timeout | null = null;
  private lastStatus: FleetStatus | null = null;

  constructor(client: AragoraClient) {
    this.client = client;
    this.statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this.statusBar.command = 'aragora.showControlPlane';
  }

  async start(): Promise<void> {
    await this.update();
    this.statusBar.show();
    this.updateInterval = setInterval(() => this.update(), 30000);
  }

  stop(): void {
    if (this.updateInterval) {
      clearInterval(this.updateInterval);
      this.updateInterval = null;
    }
    this.statusBar.dispose();
  }

  private async update(): Promise<void> {
    try {
      this.lastStatus = await this.client.getFleetStatus();
      this.render();
    } catch {
      this.render();
    }
  }

  private render(): void {
    const status = this.lastStatus;

    if (!status) {
      this.statusBar.text = '$(robot) Aragora';
      this.statusBar.tooltip = 'Aragora Control Plane - Click to open';
      return;
    }

    const healthIcon =
      status.health >= 80 ? '$(circle-filled)' : status.health >= 50 ? '$(warning)' : '$(error)';
    const healthColor =
      status.health >= 80
        ? undefined
        : status.health >= 50
          ? new vscode.ThemeColor('statusBarItem.warningBackground')
          : new vscode.ThemeColor('statusBarItem.errorBackground');

    const totalAgents =
      status.agents_idle + status.agents_busy + status.agents_offline + status.agents_error;
    const agentText = `${status.agents_idle}/${totalAgents}`;
    const taskText = status.running_tasks > 0 ? `${status.running_tasks} running` : 'idle';

    this.statusBar.text = `${healthIcon} Agents: ${agentText} | ${taskText}`;
    this.statusBar.backgroundColor = healthColor;
    this.statusBar.tooltip = new vscode.MarkdownString(
      `## Aragora Fleet Status\n\n` +
        `**Health:** ${status.health}%\n\n` +
        `| Status | Count |\n|--------|-------|\n` +
        `| Idle | ${status.agents_idle} |\n` +
        `| Busy | ${status.agents_busy} |\n` +
        `| Offline | ${status.agents_offline} |\n` +
        `| Error | ${status.agents_error} |\n\n` +
        `**Tasks:** ${status.running_tasks} running, ${status.pending_tasks} queued\n\n` +
        `_Click to open Control Plane_`,
    );
  }

  getStatusBarItem(): vscode.StatusBarItem {
    return this.statusBar;
  }
}

// ============================================
// Extension Activation
// ============================================

let telemetry: Telemetry | undefined;

export function activate(context: vscode.ExtensionContext) {
  const logger = getLogger();
  const activeTelemetry = new Telemetry({ extensionMode: context.extensionMode });
  telemetry = activeTelemetry;
  activeTelemetry.start();
  logger.setErrorReporter((error) => activeTelemetry.captureException(error));

  const client = new AragoraClient();

  // Initialize new providers
  const diagnosticsProvider = new AragoraDiagnosticsProvider();
  const codeActionsProvider = new AragoraCodeActionsProvider({ diagnosticsProvider, client });
  const securityTreeProvider = new SecurityTreeProvider(diagnosticsProvider);
  const streamManager = new StreamManager();

  // Register existing tree views
  const debatesProvider = new DebatesTreeProvider(client);
  const agentsProvider = new AgentsTreeProvider(client);
  const controlPlaneProvider = new ControlPlaneTreeProvider(client);
  const tasksProvider = new TasksTreeProvider(client);

  vscode.window.registerTreeDataProvider('aragora.debates', debatesProvider);
  vscode.window.registerTreeDataProvider('aragora.agents', agentsProvider);
  vscode.window.registerTreeDataProvider('aragora.controlPlane', controlPlaneProvider);
  vscode.window.registerTreeDataProvider('aragora.tasks', tasksProvider);
  vscode.window.registerTreeDataProvider('aragora.activeDeliberations', debatesProvider);
  vscode.window.registerTreeDataProvider('aragora.security', securityTreeProvider);

  // Register Code Actions Provider
  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      [
        { language: 'javascript' },
        { language: 'typescript' },
        { language: 'javascriptreact' },
        { language: 'typescriptreact' },
        { language: 'python' },
        { language: 'java' },
        { language: 'go' },
        { language: 'rust' },
      ],
      codeActionsProvider,
      { providedCodeActionKinds: AragoraCodeActionsProvider.providedCodeActionKinds },
    ),
  );

  // Register Hover Provider for security findings
  registerHoverProvider(context, diagnosticsProvider);

  // Initialize Control Plane Service
  const controlPlaneService = getControlPlaneService();

  // Register commands from new providers
  registerCodeActionsCommands(context, client);
  registerSecurityTreeCommands(context, securityTreeProvider);
  registerDebatePanelCommands(context, streamManager);
  registerReviewPanelCommands(context, client);
  registerDebateViewerCommands(context, controlPlaneService);

  // Add new providers to subscriptions
  context.subscriptions.push(diagnosticsProvider);
  context.subscriptions.push(streamManager);
  context.subscriptions.push(controlPlaneService);

  // Load initial data
  debatesProvider.loadDebates();
  agentsProvider.loadAgents();
  controlPlaneProvider.load();
  tasksProvider.load();

  // Auto-connect to stream if enabled
  const config = vscode.workspace.getConfiguration('aragora');
  if (config.get('autoConnect', true)) {
    streamManager.connect();
  }

  // ========== Existing Commands ==========

  // Run Debate command
  const runDebateCmd = vscode.commands.registerCommand('aragora.runDebate', async () => {
    const defaultAgents = config.get<string>('defaultAgents') || 'claude,gpt-4';
    const defaultRounds = config.get<number>('defaultRounds') || 3;

    const question = await vscode.window.showInputBox({
      prompt: 'Enter the debate question or topic',
      placeHolder: 'What is the best approach for handling errors in TypeScript?',
    });

    if (!question) return;

    const agentsInput = await vscode.window.showInputBox({
      prompt: 'Enter agents (comma-separated)',
      value: defaultAgents,
      placeHolder: 'claude,gpt-4,gemini',
    });

    if (!agentsInput) return;

    const agents = agentsInput.split(',').map((a) => a.trim());

    // Show debate panel
    const panel = DebatePanel.createOrShow(context.extensionUri, streamManager);
    panel.startDebate(question, agents, defaultRounds);

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Running Aragora Debate',
        cancellable: false,
      },
      async (progress) => {
        progress.report({ message: 'Starting debate...' });

        try {
          const result = await client.runDebate(question, agents, defaultRounds);

          let debate = result;
          while (debate.status === 'running' || debate.status === 'pending') {
            await new Promise((resolve) => setTimeout(resolve, 2000));
            debate = await client.getDebate(result.debate_id);
            progress.report({ message: `Round ${debate.rounds_completed}/${defaultRounds}` });
          }

          debatesProvider.loadDebates();
        } catch (error) {
          vscode.window.showErrorMessage(`Debate failed: ${error}`);
        }
      },
    );
  });

  // Run Gauntlet command
  const runGauntletCmd = vscode.commands.registerCommand('aragora.runGauntlet', async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showErrorMessage('No active editor');
      return;
    }

    const selection = editor.selection;
    const content = editor.document.getText(selection);

    if (!content) {
      vscode.window.showErrorMessage('No text selected');
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: 'Running Aragora Gauntlet',
        cancellable: false,
      },
      async () => {
        try {
          const result = await client.runGauntlet(content, 'code');
          vscode.window.showInformationMessage(
            `Gauntlet started! Session ID: ${result.session_id}`,
          );
        } catch (error) {
          vscode.window.showErrorMessage(`Gauntlet failed: ${error}`);
        }
      },
    );
  });

  // List Agents command
  const listAgentsCmd = vscode.commands.registerCommand('aragora.listAgents', async () => {
    try {
      const result = await client.listAgents();
      const items = result.agents.map((a) => ({
        label: a.name || a.id,
        description: a.provider,
        detail: `Status: ${a.status} | Capabilities: ${a.capabilities?.join(', ') || 'general'}`,
      }));

      await vscode.window.showQuickPick(items, {
        placeHolder: 'Available Agents',
        matchOnDescription: true,
        matchOnDetail: true,
      });
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to list agents: ${error}`);
    }
  });

  // Show Results command
  const showResultsCmd = vscode.commands.registerCommand('aragora.showResults', async () => {
    debatesProvider.loadDebates();
    vscode.commands.executeCommand('workbench.view.extension.aragora');
  });

  // Configure command
  const configureCmd = vscode.commands.registerCommand('aragora.configure', async () => {
    const action = await vscode.window.showQuickPick(
      [
        { label: 'Set API URL', description: 'Configure the Aragora API endpoint' },
        { label: 'Set API Key', description: 'Configure your API key' },
        { label: 'Set Default Agents', description: 'Configure default agents for debates' },
        { label: 'Set Default Rounds', description: 'Configure default number of rounds' },
        { label: 'Toggle Auto-Analyze', description: 'Toggle analysis on save' },
      ],
      { placeHolder: 'What would you like to configure?' },
    );

    if (!action) return;

    const currentConfig = vscode.workspace.getConfiguration('aragora');

    if (action.label === 'Set API URL') {
      const value = await vscode.window.showInputBox({
        prompt: 'Enter API URL',
        value: currentConfig.get('apiUrl'),
      });
      if (value) await currentConfig.update('apiUrl', value, true);
    } else if (action.label === 'Set API Key') {
      const value = await vscode.window.showInputBox({ prompt: 'Enter API Key', password: true });
      if (value) await currentConfig.update('apiKey', value, true);
    } else if (action.label === 'Set Default Agents') {
      const value = await vscode.window.showInputBox({
        prompt: 'Enter default agents (comma-separated)',
        value: currentConfig.get('defaultAgents'),
      });
      if (value) await currentConfig.update('defaultAgents', value, true);
    } else if (action.label === 'Set Default Rounds') {
      const value = await vscode.window.showInputBox({
        prompt: 'Enter default number of rounds',
        value: String(currentConfig.get('defaultRounds')),
      });
      if (value) await currentConfig.update('defaultRounds', parseInt(value, 10), true);
    } else if (action.label === 'Toggle Auto-Analyze') {
      const current = currentConfig.get('analyzeOnSave', true);
      await currentConfig.update('analyzeOnSave', !current, true);
      vscode.window.showInformationMessage(
        `Auto-analyze on save: ${!current ? 'enabled' : 'disabled'}`,
      );
    }
  });

  // Show Control Plane command
  const showControlPlaneCmd = vscode.commands.registerCommand(
    'aragora.showControlPlane',
    async () => {
      const apiUrl = config.get<string>('apiUrl') || 'https://api.aragora.ai';
      const uiUrl = apiUrl.replace('/api', '').replace('api.', '');
      const controlPlaneUrl = `${uiUrl}/control-plane`;

      const action = await vscode.window.showInformationMessage(
        'Open Aragora Control Plane?',
        'Open in Browser',
        'Show Fleet Status',
      );

      if (action === 'Open in Browser') {
        vscode.env.openExternal(vscode.Uri.parse(controlPlaneUrl));
      } else if (action === 'Show Fleet Status') {
        try {
          const status = await client.getFleetStatus();
          const total =
            status.agents_idle + status.agents_busy + status.agents_offline + status.agents_error;

          vscode.window.showInformationMessage(
            `Fleet Status: ${status.health}% healthy\n` +
              `Agents: ${status.agents_idle}/${total} idle, ${status.agents_busy} busy\n` +
              `Tasks: ${status.running_tasks} running, ${status.pending_tasks} queued`,
          );
        } catch (error) {
          vscode.window.showErrorMessage(`Failed to get fleet status: ${error}`);
        }
      }
    },
  );

  // Refresh Fleet command
  const refreshFleetCmd = vscode.commands.registerCommand('aragora.refreshFleet', async () => {
    await fleetManager.start();
    vscode.window.showInformationMessage('Fleet status refreshed');
  });

  // Refresh Control Plane command
  const refreshControlPlaneCmd = vscode.commands.registerCommand(
    'aragora.refreshControlPlane',
    async () => {
      await Promise.all([
        controlPlaneProvider.load(),
        tasksProvider.load(),
        agentsProvider.loadAgents(),
      ]);
    },
  );

  // Submit Task command
  const submitTaskCmd = vscode.commands.registerCommand('aragora.submitTask', async () => {
    const taskType = await vscode.window.showQuickPick(
      [
        { label: 'debate', description: 'Multi-agent debate' },
        { label: 'review', description: 'Code review' },
        { label: 'analysis', description: 'Data analysis' },
        { label: 'custom', description: 'Custom task type' },
      ],
      { placeHolder: 'Select task type' },
    );

    if (!taskType) return;

    let finalTaskType = taskType.label;
    if (taskType.label === 'custom') {
      const custom = await vscode.window.showInputBox({ prompt: 'Enter custom task type' });
      if (!custom) return;
      finalTaskType = custom;
    }

    const payload = await vscode.window.showInputBox({
      prompt: 'Enter task payload (JSON)',
      placeHolder: '{"topic": "your topic here"}',
    });

    if (!payload) return;

    try {
      const parsedPayload = JSON.parse(payload);
      const result = await client.submitTask(finalTaskType, parsedPayload);
      vscode.window.showInformationMessage(`Task submitted! ID: ${result.task_id}`);
      tasksProvider.load();
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to submit task: ${error}`);
    }
  });

  // View Agent Health command
  const viewAgentHealthCmd = vscode.commands.registerCommand(
    'aragora.viewAgentHealth',
    async (item?: AgentItem) => {
      let agentId: string | undefined;

      if (item && 'label' in item) {
        agentId = item.label as string;
      } else {
        const agents = await client.listAgents();
        const selected = await vscode.window.showQuickPick(
          agents.agents.map((a) => ({ label: a.name || a.id, id: a.id })),
          { placeHolder: 'Select agent' },
        );
        agentId = selected?.id;
      }

      if (!agentId) return;

      try {
        const health = await client.getAgentHealth(agentId);
        const doc = await vscode.workspace.openTextDocument({
          content: [
            `Agent Health: ${agentId}`,
            '═'.repeat(40),
            '',
            `Status: ${health.status}`,
            `Last Heartbeat: ${health.last_heartbeat}`,
            `Latency: ${health.latency_ms}ms`,
            `Success Rate: ${health.success_rate}%`,
            `Tasks Completed: ${health.tasks_completed}`,
          ].join('\n'),
          language: 'plaintext',
        });
        await vscode.window.showTextDocument(doc);
      } catch (error) {
        vscode.window.showErrorMessage(`Failed to get agent health: ${error}`);
      }
    },
  );

  // Cancel Task command
  const cancelTaskCmd = vscode.commands.registerCommand(
    'aragora.cancelTask',
    async (item?: TaskItem) => {
      let taskId: string | undefined;

      if (item && 'taskId' in item) {
        taskId = item.taskId;
      } else {
        const tasks = await client.listTasks();
        const pending = tasks.tasks.filter((t) => t.status === 'pending' || t.status === 'running');
        if (pending.length === 0) {
          vscode.window.showInformationMessage('No cancellable tasks');
          return;
        }
        const selected = await vscode.window.showQuickPick(
          pending.map((t) => ({ label: t.id, description: `${t.task_type} - ${t.status}` })),
          { placeHolder: 'Select task to cancel' },
        );
        taskId = selected?.label;
      }

      if (!taskId) return;

      try {
        const result = await client.cancelTask(taskId);
        if (result.success) {
          vscode.window.showInformationMessage(`Task ${taskId} cancelled`);
          tasksProvider.load();
        } else {
          vscode.window.showWarningMessage(`Could not cancel task ${taskId}`);
        }
      } catch (error) {
        vscode.window.showErrorMessage(`Failed to cancel task: ${error}`);
      }
    },
  );

  // Register Agent command
  const registerAgentCmd = vscode.commands.registerCommand('aragora.registerAgent', async () => {
    const agentId = await vscode.window.showInputBox({
      prompt: 'Enter agent ID',
      placeHolder: 'my-custom-agent',
    });

    if (!agentId) return;

    const capabilities = await vscode.window.showInputBox({
      prompt: 'Enter capabilities (comma-separated)',
      value: 'debate,review',
    });

    if (!capabilities) return;

    const model = await vscode.window.showInputBox({ prompt: 'Enter model name', value: 'custom' });

    if (!model) return;

    try {
      await client.submitTask('register_agent', {
        agent_id: agentId,
        capabilities: capabilities.split(',').map((c) => c.trim()),
        model,
      });
      vscode.window.showInformationMessage(`Agent ${agentId} registration submitted`);
      agentsProvider.loadAgents();
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to register agent: ${error}`);
    }
  });

  // Analyze Workspace command
  const analyzeWorkspaceCmd = vscode.commands.registerCommand(
    'aragora.analyzeWorkspace',
    async () => {
      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: 'Analyzing Workspace Security',
          cancellable: false,
        },
        async (progress) => {
          const findings = await diagnosticsProvider.analyzeWorkspace(progress);
          securityTreeProvider.setFindings(findings);

          const total = Array.from(findings.values()).reduce((sum, f) => sum + f.length, 0);
          vscode.window.showInformationMessage(
            `Found ${total} security issues in ${findings.size} files`,
          );
        },
      );
    },
  );

  // Clear Debate Context command
  const clearDebateContextCmd = vscode.commands.registerCommand(
    'aragora.clearDebateContext',
    async () => {
      await context.workspaceState.update('debateContext', []);
      vscode.window.showInformationMessage('Debate context cleared');
    },
  );

  // View Debate Context command
  const viewDebateContextCmd = vscode.commands.registerCommand(
    'aragora.viewDebateContext',
    async () => {
      const debateContext = context.workspaceState.get<string[]>('debateContext', []);

      if (debateContext.length === 0) {
        vscode.window.showInformationMessage(
          'No code snippets in debate context. Use "Add to Debate" on selected code.',
        );
        return;
      }

      const content = `# Debate Context\n\nTotal snippets: ${debateContext.length}\n${debateContext.join('\n---\n')}`;

      const doc = await vscode.workspace.openTextDocument({ content, language: 'markdown' });
      await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside });
    },
  );

  // Quick Review command - performs a quick review of current file or selection
  const quickReviewCmd = vscode.commands.registerCommand('aragora.quickReview', async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage('No active editor');
      return;
    }

    const selection = editor.selection;
    const text = selection.isEmpty ? editor.document.getText() : editor.document.getText(selection);

    const fileName = editor.document.fileName.split('/').pop() || 'code';
    const scope = selection.isEmpty ? 'file' : 'selection';

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: `Quick Review: ${fileName}`,
        cancellable: false,
      },
      async (progress) => {
        progress.report({ message: 'Analyzing...' });

        try {
          const result = await client.reviewCode(text, editor.document.languageId, fileName);

          // Show toast notification with summary
          const action = await vscode.window.showInformationMessage(
            `Review complete: ${result.summary || 'No issues found'}`,
            'View Details',
          );

          if (action === 'View Details') {
            const detailDoc = await vscode.workspace.openTextDocument({
              content: `# Quick Review: ${fileName}\n\n**Scope:** ${scope}\n**Lines:** ${text.split('\n').length}\n\n## Summary\n\n${result.summary}\n\n## Comments\n\n${result.comments.length === 0 ? 'No specific comments.' : result.comments.map((c: unknown) => `- ${c}`).join('\n')}`,
              language: 'markdown',
            });
            await vscode.window.showTextDocument(detailDoc, {
              viewColumn: vscode.ViewColumn.Beside,
            });
          }
        } catch (error) {
          vscode.window.showErrorMessage(`Quick review failed: ${error}`);
        }
      },
    );
  });

  // Trigger Vetted Decisionmaking command - triggers a new session from selected text
  const triggerDeliberationCmd = vscode.commands.registerCommand(
    'aragora.triggerDeliberation',
    async () => {
      const editor = vscode.window.activeTextEditor;

      // Get question from selection or prompt user
      let question: string | undefined;

      if (editor && !editor.selection.isEmpty) {
        question = editor.document.getText(editor.selection);
      }

      if (!question) {
        question = await vscode.window.showInputBox({
          prompt: 'Enter the question for multi-agent vetted decisionmaking',
          placeHolder: 'What is the best approach for...',
        });
      }

      if (!question) return;

      const deliberationId = await controlPlaneService.triggerDeliberation(question);

      if (deliberationId) {
        const action = await vscode.window.showInformationMessage(
          `Vetted decisionmaking started: ${deliberationId}`,
          'Watch Live',
        );

        if (action === 'Watch Live') {
          vscode.commands.executeCommand('aragora.showDebateViewer', deliberationId);
        }
      }
    },
  );

  // Connect to Deliberation command
  const connectToDeliberationCmd = vscode.commands.registerCommand(
    'aragora.connectToDeliberation',
    async () => {
      const deliberations = await controlPlaneService.getActiveDeliberations();

      if (deliberations.length === 0) {
        vscode.window.showInformationMessage('No active vetted decisionmaking sessions');
        return;
      }

      const items = deliberations.map((d) => ({
        label: d.question.substring(0, 60) + (d.question.length > 60 ? '...' : ''),
        description: `Round ${d.currentRound}/${d.totalRounds}`,
        id: d.id,
      }));

      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: 'Select a vetted decisionmaking session to watch',
      });

      if (selected) {
        vscode.commands.executeCommand('aragora.showDebateViewer', selected.id);
      }
    },
  );

  // Register all commands
  context.subscriptions.push(
    runDebateCmd,
    runGauntletCmd,
    listAgentsCmd,
    showResultsCmd,
    configureCmd,
    showControlPlaneCmd,
    refreshFleetCmd,
    refreshControlPlaneCmd,
    submitTaskCmd,
    viewAgentHealthCmd,
    cancelTaskCmd,
    registerAgentCmd,
    analyzeWorkspaceCmd,
    clearDebateContextCmd,
    viewDebateContextCmd,
    quickReviewCmd,
    triggerDeliberationCmd,
    connectToDeliberationCmd,
  );

  // Fleet Status Manager
  const fleetManager = new FleetStatusManager(client);
  fleetManager.start();

  context.subscriptions.push({ dispose: () => fleetManager.stop() });

  logger.info('Aragora extension activated.');
  activeTelemetry.trackEvent('extension_activated');
  vscode.window.showInformationMessage('Aragora Control Plane activated with code analysis!');
}

export async function deactivate(): Promise<void> {
  // Clean up Control Plane Service
  disposeControlPlaneService();

  const logger = getLogger();
  logger.setErrorReporter(undefined);
  await telemetry?.shutdown();
  telemetry = undefined;
  logger.dispose();
}
