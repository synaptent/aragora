/**
 * Control Plane Service for VS Code Extension
 *
 * Provides connectivity to the Aragora Control Plane for:
 * - Real-time deliberation streaming
 * - Task management
 * - Agent monitoring
 */

import * as vscode from 'vscode';
import { getLogger } from '../logger';

const logger = getLogger();

/** Active deliberation information */
export interface Deliberation {
  id: string;
  question: string;
  status: 'running' | 'completed' | 'failed';
  currentRound: number;
  totalRounds: number;
  agents: string[];
  startTime: number;
  endTime?: number;
  consensusReached?: boolean;
  confidence?: number;
}

/** Event types from the control plane */
export type ControlPlaneEventType =
  | 'deliberation_started'
  | 'deliberation_progress'
  | 'deliberation_round'
  | 'deliberation_vote'
  | 'deliberation_consensus'
  | 'deliberation_completed'
  | 'deliberation_failed'
  | 'deliberation_sla_warning'
  | 'agent_registered'
  | 'agent_updated'
  | 'agent_heartbeat'
  | 'task_submitted'
  | 'task_completed'
  | 'task_failed'
  | 'connection_status';

/** Event payload from control plane */
export interface ControlPlaneEvent {
  type: ControlPlaneEventType;
  data: Record<string, unknown>;
  timestamp: number;
}

export type ControlPlaneEventHandler = (event: ControlPlaneEvent) => void;

/**
 * Service for interacting with the Aragora Control Plane
 */
export class ControlPlaneService implements vscode.Disposable {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private pingInterval: NodeJS.Timeout | null = null;
  private handlers: Set<ControlPlaneEventHandler> = new Set();
  private connectionStatus: 'connected' | 'disconnected' | 'connecting' = 'disconnected';
  private disposables: vscode.Disposable[] = [];

  /** Active deliberations being tracked */
  private activeDeliberations: Map<string, Deliberation> = new Map();

  constructor() {
    // Register commands
    this.disposables.push(
      vscode.commands.registerCommand('aragora.connectControlPlane', () => this.connect()),
    );
    this.disposables.push(
      vscode.commands.registerCommand('aragora.disconnectControlPlane', () => this.disconnect()),
    );
  }

  /**
   * Connect to the Control Plane WebSocket
   */
  async connect(): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return;
    }

    this.setConnectionStatus('connecting');

    const config = vscode.workspace.getConfiguration('aragora');
    const apiUrl = config.get<string>('apiUrl') || 'http://localhost:8080';
    const apiKey = config.get<string>('apiKey') || '';

    // Convert HTTP to WebSocket URL for control plane endpoint
    const wsUrl = apiUrl.replace(/^http/, 'ws') + '/api/v1/control-plane/stream';

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.setConnectionStatus('connected');
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;

        // Send authentication if we have an API key
        if (apiKey) {
          this.ws?.send(JSON.stringify({ type: 'auth', token: apiKey }));
        }

        // Subscribe to deliberation events
        this.ws?.send(
          JSON.stringify({ type: 'subscribe', channels: ['deliberations', 'agents', 'tasks'] }),
        );

        // Start ping interval
        this.startPingInterval();

        vscode.window.showInformationMessage('Connected to Aragora Control Plane');

        // Emit connection event
        this.emitEvent({
          type: 'connection_status',
          data: { status: 'connected' },
          timestamp: Date.now(),
        });
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as ControlPlaneEvent;
          this.handleEvent(data);
        } catch (error) {
          logger.error('Failed to parse control plane event:', error);
        }
      };

      this.ws.onerror = (error) => {
        logger.error('Control plane WebSocket error:', error);
      };

      this.ws.onclose = (event) => {
        this.setConnectionStatus('disconnected');
        this.stopPingInterval();

        this.emitEvent({
          type: 'connection_status',
          data: { status: 'disconnected' },
          timestamp: Date.now(),
        });

        if (event.code !== 1000) {
          this.scheduleReconnect();
        }
      };
    } catch (error) {
      logger.error('Failed to connect to control plane:', error);
      this.setConnectionStatus('disconnected');
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from the Control Plane
   */
  disconnect(): void {
    this.stopPingInterval();
    this.cancelReconnect();

    if (this.ws) {
      this.ws.close(1000, 'User disconnect');
      this.ws = null;
    }

    this.setConnectionStatus('disconnected');
  }

  /**
   * Subscribe to control plane events
   */
  subscribe(handler: ControlPlaneEventHandler): vscode.Disposable {
    this.handlers.add(handler);
    return { dispose: () => this.handlers.delete(handler) };
  }

  /**
   * Get current connection status
   */
  getConnectionStatus(): 'connected' | 'disconnected' | 'connecting' {
    return this.connectionStatus;
  }

  /**
   * Get all active deliberations
   */
  async getActiveDeliberations(): Promise<Deliberation[]> {
    // If connected, also fetch from API
    if (this.connectionStatus === 'connected') {
      try {
        const config = vscode.workspace.getConfiguration('aragora');
        const apiUrl = config.get<string>('apiUrl') || 'http://localhost:8080';
        const apiKey = config.get<string>('apiKey') || '';

        const response = await fetch(`${apiUrl}/api/v1/control-plane/deliberations`, {
          headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
        });

        if (response.ok) {
          const data = (await response.json()) as { deliberations: Deliberation[] };
          // Update local cache
          for (const delib of data.deliberations) {
            this.activeDeliberations.set(delib.id, delib);
          }
        }
      } catch (error) {
        logger.error('Failed to fetch vetted decisionmaking sessions:', error);
      }
    }

    return Array.from(this.activeDeliberations.values());
  }

  /**
   * Trigger a new deliberation
   */
  async triggerDeliberation(
    question: string,
    agents?: string[],
    rounds?: number,
  ): Promise<string | null> {
    const config = vscode.workspace.getConfiguration('aragora');
    const apiUrl = config.get<string>('apiUrl') || 'http://localhost:8080';
    const apiKey = config.get<string>('apiKey') || '';

    try {
      const response = await fetch(`${apiUrl}/api/v1/control-plane/deliberations`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey && { Authorization: `Bearer ${apiKey}` }),
        },
        body: JSON.stringify({
          question,
          agents: agents || ['claude', 'gpt-4'],
          rounds: rounds || 3,
        }),
      });

      if (response.ok) {
        const data = (await response.json()) as { deliberation_id: string };
        return data.deliberation_id;
      }

      throw new Error(`Failed to trigger deliberation: ${response.statusText}`);
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to trigger deliberation: ${error}`);
      return null;
    }
  }

  /**
   * Connect to a specific deliberation stream
   */
  connectToDeliberation(deliberationId: string): vscode.Disposable {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({ type: 'subscribe_deliberation', deliberation_id: deliberationId }),
      );
    }

    return {
      dispose: () => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(
            JSON.stringify({ type: 'unsubscribe_deliberation', deliberation_id: deliberationId }),
          );
        }
      },
    };
  }

  private handleEvent(event: ControlPlaneEvent): void {
    // Update local state based on event type
    switch (event.type) {
      case 'deliberation_started': {
        const delib: Deliberation = {
          id: event.data.deliberation_id as string,
          question: event.data.question as string,
          status: 'running',
          currentRound: 0,
          totalRounds: event.data.total_rounds as number,
          agents: event.data.agents as string[],
          startTime: event.timestamp,
        };
        this.activeDeliberations.set(delib.id, delib);
        break;
      }

      case 'deliberation_round': {
        const id = event.data.deliberation_id as string;
        const delib = this.activeDeliberations.get(id);
        if (delib) {
          delib.currentRound = event.data.round as number;
        }
        break;
      }

      case 'deliberation_consensus':
      case 'deliberation_completed': {
        const id = event.data.deliberation_id as string;
        const delib = this.activeDeliberations.get(id);
        if (delib) {
          delib.status = 'completed';
          delib.endTime = event.timestamp;
          delib.consensusReached = event.data.consensus_reached as boolean | undefined;
          delib.confidence = event.data.confidence as number | undefined;
        }
        break;
      }

      case 'deliberation_failed': {
        const id = event.data.deliberation_id as string;
        const delib = this.activeDeliberations.get(id);
        if (delib) {
          delib.status = 'failed';
          delib.endTime = event.timestamp;
        }
        break;
      }
    }

    // Emit to all handlers
    this.emitEvent(event);
  }

  private emitEvent(event: ControlPlaneEvent): void {
    for (const handler of this.handlers) {
      try {
        handler(event);
      } catch (error) {
        logger.error('Handler error:', error);
      }
    }
  }

  private setConnectionStatus(status: 'connected' | 'disconnected' | 'connecting'): void {
    this.connectionStatus = status;
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      return;
    }

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
      this.connect();
    }, this.reconnectDelay);
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startPingInterval(): void {
    this.pingInterval = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  }

  private stopPingInterval(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  dispose(): void {
    this.disconnect();
    this.disposables.forEach((d) => d.dispose());
  }
}

/** Global service instance */
let _controlPlaneService: ControlPlaneService | null = null;

export function getControlPlaneService(): ControlPlaneService {
  if (!_controlPlaneService) {
    _controlPlaneService = new ControlPlaneService();
  }
  return _controlPlaneService;
}

export function disposeControlPlaneService(): void {
  if (_controlPlaneService) {
    _controlPlaneService.dispose();
    _controlPlaneService = null;
  }
}
