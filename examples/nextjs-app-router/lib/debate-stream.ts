import type { AragoraWebSocket, WebSocketEvent } from '@aragora/sdk';

export interface StreamEvent {
  type: string;
  agent?: string;
  content?: string;
  timestamp: string;
}

interface StreamHandlers {
  onEvent: (event: StreamEvent) => void;
  onConnected: (connected: boolean) => void;
  onError: (error: string | null) => void;
}

type DisplayableEvent = Omit<WebSocketEvent, 'timestamp'> & {
  timestamp: string | number;
  agent?: string;
};

export function displayEvent(event: DisplayableEvent, debateId: string): StreamEvent | null {
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const nestedId = 'debate_id' in data && typeof data.debate_id === 'string'
    ? data.debate_id : undefined;
  const nestedLoopId = 'loop_id' in data && typeof data.loop_id === 'string'
    ? data.loop_id : undefined;
  const id = event.debate_id || event.loop_id || nestedId || nestedLoopId;
  if (id !== debateId) return null;
  let timestamp = event.timestamp;
  if (typeof timestamp === 'number') {
    // Server StreamEvent envelopes carry Unix seconds, including fractions.
    const date = new Date(timestamp * 1000);
    if (!Number.isFinite(date.getTime())) return null;
    timestamp = date.toISOString();
  }
  return {
    type: event.type,
    timestamp,
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
