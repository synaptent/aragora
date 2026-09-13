import type { AragoraWebSocket, WebSocketEvent } from '@aragora/sdk';

export interface StreamEvent {
  type: string;
  agent?: string;
  content?: string;
  timestamp?: string;
}

type IncomingEvent = Omit<WebSocketEvent, 'timestamp'> & {
  timestamp?: unknown;
  agent?: unknown;
};

interface StreamHandlers {
  onEvent: (event: StreamEvent) => void;
  onConnected: (connected: boolean) => void;
  onError: (error: string | null) => void;
}

function eventTimestamp(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    // Server StreamEvent timestamps use seconds; the SDK type declares ISO strings.
    const date = new Date(value * 1000);
    return Number.isFinite(date.getTime()) ? date.toISOString() : undefined;
  }
  if (typeof value === 'string' && Number.isFinite(Date.parse(value))) return value;
  return undefined;
}

export function displayEvent(event: IncomingEvent, debateId: string): StreamEvent | null {
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const nestedId = 'debate_id' in data && typeof data.debate_id === 'string'
    ? data.debate_id : undefined;
  const nestedLoopId = 'loop_id' in data && typeof data.loop_id === 'string'
    ? data.loop_id : undefined;
  const id = event.debate_id || event.loop_id || nestedId || nestedLoopId;
  if (id !== debateId) return null;
  return {
    type: event.type,
    timestamp: eventTimestamp(event.timestamp),
    agent: typeof event.agent === 'string' && event.agent ? event.agent
      : 'agent' in data && typeof data.agent === 'string' ? data.agent : undefined,
    content: 'content' in data && typeof data.content === 'string' ? data.content : undefined,
  };
}

export function connectDebateStream(
  stream: AragoraWebSocket,
  debateId: string,
  handlers: StreamHandlers,
): () => void {
  let disposed = false;
  const reportError = (error: unknown) => {
    if (disposed) return;
    handlers.onError(error instanceof Error ? error.message : 'Failed to connect');
    handlers.onConnected(false);
  };
  const unsubscribe = [
    stream.on('connected', () => {
      if (disposed) return;
      // The SDK reconnects without the initial query; restore the subscription.
      stream.subscribe(debateId);
      handlers.onError(null);
      handlers.onConnected(true);
    }),
    stream.on('message', event => {
      if (disposed) return;
      const display = displayEvent(event, debateId);
      if (display) handlers.onEvent(display);
    }),
    stream.on('error', reportError),
    stream.on('disconnected', () => {
      if (!disposed) handlers.onConnected(false);
    }),
  ];
  const cleanup = () => {
    if (disposed) return;
    disposed = true;
    unsubscribe.forEach(remove => remove());
    stream.disconnect();
  };
  try {
    void stream.connect(debateId).then(() => {
      if (disposed) stream.disconnect();
    }, reportError);
  } catch (error) {
    reportError(error);
    cleanup();
  }
  return cleanup;
}
