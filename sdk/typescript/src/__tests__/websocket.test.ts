import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AragoraClient } from '../client';
import { ConnectionError, isRetryableError } from '../errors';
import { AragoraWebSocket, streamDebate, streamDebateById } from '../websocket';
import type { WebSocketEvent } from '../types';

// Exercise the real SDK socket handlers without network or wall-clock waits.
class FakeSocket {
  static latest: FakeSocket;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  close = vi.fn();
  send = vi.fn();

  constructor(public url: string) { FakeSocket.latest = this; }
  open() { this.onopen?.(); }
  message(event: WebSocketEvent) { this.onmessage?.({ data: JSON.stringify(event) }); }
  drop(code = 1006) { this.onclose?.({ code, reason: 'untrusted remote reason' }); }
}

const config = { baseUrl: 'https://example.test' };
const event = (type: WebSocketEvent['type'], content: string = type, debateId = 'debate-1'): WebSocketEvent => ({
  type, debate_id: debateId, timestamp: '2026-09-06T00:00:00Z', data: { content },
});
const done = { done: true, value: undefined };

describe('streamDebate terminal delivery', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', FakeSocket);
  });
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function checkCleanup(socket: FakeSocket, off: { mock: { calls: unknown[][] } }) {
    expect(socket.close).toHaveBeenCalledExactlyOnceWith(1000, 'Client disconnect');
    expect(off.mock.calls.map(([name]) => name)).toEqual(['message', 'error', 'disconnected']);
    expect(vi.getTimerCount()).toBe(0);
  }

  it.each(['debate_end', 'error'] as const)('drains pre-pull work and the genuine %s event', async (terminal) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    const events = [event('agent_message', 'one'), event('agent_message', 'two'), event(terminal)];
    events.forEach((value) => socket.message(value));
    expect(await first).toEqual({ done: false, value: events[0] });
    expect(await stream.next()).toEqual({ done: false, value: events[1] });
    expect(await stream.next()).toEqual({ done: false, value: events[2] });
    expect(await stream.next()).toEqual(done);
    checkCleanup(socket, off);
  });

  it('preserves order when terminal arrives between consumer pulls', async () => {
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    await Promise.resolve(); // Wait for the iterator to request its first event.
    socket.message(event('agent_message', 'one'));
    expect((await first).value).toEqual(event('agent_message', 'one'));
    socket.message(event('agent_message', 'two'));
    socket.message(event('debate_end'));
    expect((await stream.next()).value).toEqual(event('agent_message', 'two'));
    expect((await stream.next()).value).toEqual(event('debate_end'));
    expect(await stream.next()).toEqual(done);
  });

  it.each([1000, 1006])('rejects a pending pull on non-terminal close %s', async (code) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message'));
    await first;
    const pending = stream.next();
    const rejected = expect(pending).rejects.toBeInstanceOf(ConnectionError);
    socket.drop(code);
    await rejected;
    expect(await stream.next()).toEqual(done);
    checkCleanup(socket, off);
  });

  it('drains accepted work before reporting a between-pull disconnect', async () => {
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message', 'one'));
    expect((await first).value).toEqual(event('agent_message', 'one'));
    socket.message(event('agent_message', 'two'));
    socket.drop();
    expect((await stream.next()).value).toEqual(event('agent_message', 'two'));
    await expect(stream.next()).rejects.toMatchObject({ name: 'ConnectionError' });
    expect(await stream.next()).toEqual(done);
  });

  it('retains transport errors received between pulls, after buffered work', async () => {
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message', 'one'));
    await first;
    socket.message(event('agent_message', 'two'));
    socket.onerror?.();
    expect((await stream.next()).value).toEqual(event('agent_message', 'two'));
    await expect(stream.next()).rejects.toBeInstanceOf(ConnectionError);
  });

  it.each(['same-turn', 'later-turn'] as const)('types an error followed by %s close after draining accepted work', async (timing) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message', 'one'));
    await first;
    socket.message(event('agent_message', 'two'));
    socket.onerror?.();
    if (timing === 'later-turn') await vi.advanceTimersByTimeAsync(0);
    socket.drop();
    expect((await stream.next()).value).toEqual(event('agent_message', 'two'));
    const failure = await stream.next().catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ConnectionError);
    expect(isRetryableError(failure)).toBe(true);
    checkCleanup(socket, off);
  });

  it('reports a malformed frame without exposing its raw payload in the error', async () => {
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message'));
    await first;
    socket.onmessage?.({ data: 'private malformed payload' });
    const failure = await stream.next().catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ConnectionError);
    expect(String(failure)).not.toContain('private malformed payload');
  });

  it('rejects a waiting pull on transport error', async () => {
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message'));
    await first;
    const rejected = expect(stream.next()).rejects.toBeInstanceOf(ConnectionError);
    socket.onerror?.();
    await rejected;
    expect(socket.close).toHaveBeenCalledOnce();
  });

  it('does not replace a genuine terminal event with later messages or transport failures', async () => {
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('debate_end'));
    socket.message(event('agent_message', 'too late'));
    socket.onerror?.();
    socket.drop();
    expect((await first).value).toEqual(event('debate_end'));
    expect(await stream.next()).toEqual(done);
  });

  it('cleans up handlers and socket when connection establishment fails', async () => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    const rejected = expect(first).rejects.toBeInstanceOf(ConnectionError);
    const socket = FakeSocket.latest;
    socket.onerror?.();
    await rejected;
    checkCleanup(socket, off);
  });

  it('terminates setup when the socket closes without opening or emitting an error', async () => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    let failure: unknown;
    void first.catch((error: unknown) => { failure = error; });
    const socket = FakeSocket.latest;
    socket.drop();
    await vi.advanceTimersByTimeAsync(0);
    expect(failure).toBeInstanceOf(ConnectionError);
    checkCleanup(socket, off);
  });

  it.each(['debate_end', 'disconnect'] as const)('releases transport on %s even while the consumer pauses', async (terminal) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config, { reconnectDelay: 10 });
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message', 'one'));
    await first;
    socket.message(event('agent_message', 'two'));
    if (terminal === 'disconnect') socket.drop();
    else socket.message(event('debate_end'));
    await vi.advanceTimersByTimeAsync(100);
    expect(FakeSocket.latest).toBe(socket);
    checkCleanup(socket, off);
    expect((await stream.next()).value).toEqual(event('agent_message', 'two'));
    if (terminal === 'disconnect') {
      await expect(stream.next()).rejects.toBeInstanceOf(ConnectionError);
    } else {
      expect((await stream.next()).value).toEqual(event('debate_end'));
      expect(await stream.next()).toEqual(done);
    }
    checkCleanup(socket, off);
  });

  it.each(['return', 'throw'] as const)('cleans up on consumer %s after a delivered event', async (method) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message'));
    await first;
    if (method === 'return') {
      expect(await stream.return()).toEqual(done);
    } else {
      const failure = new Error('consumer stopped');
      await expect(stream.throw(failure)).rejects.toBe(failure);
    }
    checkCleanup(socket, off);
  });

  it.each(['by-id', 'client', 'all'] as const)('preserves %s wrapper filtering and server event payloads', async (wrapper) => {
    const client = new AragoraClient(config);
    const stream = wrapper === 'by-id' ? streamDebateById(config, 'debate-1')
      : wrapper === 'client' ? client.streamDebate('debate-1')
      : client.streamAllDebates({ debateId: 'debate-1' });
    const first = stream.next();
    const socket = FakeSocket.latest;
    expect(socket.url).toContain('debate_id=debate-1');
    socket.open();
    socket.message(event('debate_end', 'unrelated', 'debate-2'));
    const warning: WebSocketEvent = { type: 'warning', timestamp: 'now', data: { message: 'notice' } };
    socket.message(warning);
    socket.message(event('consensus'));
    socket.message(event('debate_end'));
    expect((await first).value).toEqual(warning);
    expect((await stream.next()).value).toEqual(event('consensus'));
    expect((await stream.next()).value).toEqual(event('debate_end'));
    expect(await stream.next()).toEqual(done);
  });
});
