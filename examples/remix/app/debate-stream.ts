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

export function displayEvent(event: WebSocketEvent, debateId: string): StreamEvent | null {
  const data = event.data && typeof event.data === 'object' ? event.data : {};
  const nestedId = 'debate_id' in data ? data.debate_id : undefined;
  const id = event.debate_id ?? event.loop_id ?? nestedId;
  if (id !== debateId) return null;
  return {
    type: event.type,
    timestamp: event.timestamp,
    agent: 'agent' in data && typeof data.agent === 'string' ? data.agent : undefined,
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
