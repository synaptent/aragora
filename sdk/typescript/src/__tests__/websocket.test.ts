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
  it.each([
    [1000, false], [1001, true], [1002, false], [1003, false], [1005, false],
    [1006, true], [1007, false], [1008, false], [1009, false], [1010, false],
    [1011, true], [1012, true], [1013, true], [1015, false],
    [4003, false], [4029, true], [4999, false],
  ])('exposes close %i with retryable=%s after buffered work', async (code, retryable) => {
    for (const waiting of [false, true]) {
      const stream = streamDebateById(config, 'debate-1');
      const first = stream.next();
      const socket = FakeSocket.latest;
      socket.open(); socket.message(event('agent_message', 'first')); await first;
      socket.message(event('agent_message', 'saved'));
      if (waiting) expect((await stream.next()).value).toEqual(event('agent_message', 'saved'));
      const pending = waiting ? stream.next().catch((error: unknown) => error) : undefined;
      socket.drop(code as number);
      if (!waiting) expect((await stream.next()).value).toEqual(event('agent_message', 'saved'));
      const failure = waiting ? await pending : await stream.next().catch((error: unknown) => error);
      expect(failure).toBeInstanceOf(ConnectionError);
      expect(failure).toMatchObject({ code: `WS_CLOSE_${code}`, errorCode: `WS_CLOSE_${code}`, retryable, responseBody: { code } });
      expect(isRetryableError(failure)).toBe(retryable);
      expect(JSON.stringify(failure)).not.toContain('untrusted remote reason');
      expect(socket.close).toHaveBeenCalledOnce();
      expect(vi.getTimerCount()).toBe(0);
      expect(await stream.next()).toEqual(done);
    }
  });

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
    await vi.advanceTimersByTimeAsync(1000);
    await expect(stream.next()).rejects.toBeInstanceOf(ConnectionError);
  });

  it.each([1006, 1008, 4003, 4029].flatMap((code) =>
    ['connecting', 'waiting', 'paused'].flatMap((phase) =>
      [0, 10].map((delay) => [code, phase, delay] as const))))(
    'preserves error-before-close %i in %s with delay %i', async (code, phase, delay) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    let pending: Promise<unknown> = first.catch((error: unknown) => error);
    if (phase !== 'connecting') {
      socket.open(); socket.message(event('agent_message', 'one')); await first;
      socket.message(event('agent_message', 'two'));
      if (phase === 'waiting') {
        expect((await stream.next()).value).toEqual(event('agent_message', 'two'));
        pending = stream.next().catch((error: unknown) => error);
      }
    }
    socket.onerror?.();
    await vi.advanceTimersByTimeAsync(delay);
    socket.drop(code);
    if (phase === 'paused') {
      expect((await stream.next()).value).toEqual(event('agent_message', 'two'));
      pending = stream.next().catch((error: unknown) => error);
    }
    const failure = await pending;
    expect(failure).toBeInstanceOf(ConnectionError);
    expect(failure).toMatchObject({ code: `WS_CLOSE_${code}`, errorCode: `WS_CLOSE_${code}`, responseBody: { code } });
    expect(isRetryableError(failure)).toBe(code === 1006 || code === 4029);
    expect(JSON.stringify(failure)).not.toContain('untrusted remote reason');
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
    expect(isRetryableError(failure)).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('rejects a waiting pull after the transport close-observation deadline', async () => {
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message'));
    await first;
    const rejected = expect(stream.next()).rejects.toBeInstanceOf(ConnectionError);
    socket.onerror?.();
    await vi.advanceTimersByTimeAsync(1000);
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
    await vi.advanceTimersByTimeAsync(1000);
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

  it.each(['return', 'throw'].flatMap((method) => [false, true].map((fault) => [method, fault] as const)))(
    'cleans up on consumer %s after a delivered event, observing close=%s', async (method, fault) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next();
    const socket = FakeSocket.latest;
    socket.open();
    socket.message(event('agent_message'));
    await first;
    if (fault) socket.onerror?.();
    if (method === 'return') {
      expect(await stream.return()).toEqual(done);
    } else {
      const failure = new Error('consumer stopped');
      await expect(stream.throw(failure)).rejects.toBe(failure);
    }
    checkCleanup(socket, off);
  });

  it.each(['connecting', 'waiting', 'paused'])('bounds repeated errors and ignores a late close in %s', async (phase) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    let settled = false;
    let pending: Promise<unknown> = stream.next().catch((error: unknown) => error);
    const socket = FakeSocket.latest;
    if (phase !== 'connecting') {
      socket.open(); socket.message(event('agent_message')); await pending;
      pending = phase === 'waiting' ? stream.next().catch((error: unknown) => error) : new Promise(() => {});
    }
    void pending.then(() => { settled = true; });
    socket.onerror?.();
    await vi.advanceTimersByTimeAsync(500); socket.onerror?.();
    await vi.advanceTimersByTimeAsync(499);
    expect(settled).toBe(false); expect(socket.close).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    checkCleanup(socket, off); // Even a paused consumer releases the transport.
    if (phase === 'paused') pending = stream.next().catch((error: unknown) => error);
    const failure = await pending;
    expect(failure).toBeInstanceOf(ConnectionError);
    expect(isRetryableError(failure)).toBe(false);
    expect(failure).toMatchObject({ code: undefined, errorCode: undefined, responseBody: undefined });
    const before = JSON.stringify(failure);
    socket.drop(4029); socket.onerror?.(); await vi.advanceTimersByTimeAsync(1000);
    expect(JSON.stringify(failure)).toBe(before); checkCleanup(socket, off);
  });

  it.each([true, false])('finalizes once at the deadline, close callback first=%s', async (closeFirst) => {
    const stream = streamDebate(config);
    const first = stream.next(); const socket = FakeSocket.latest;
    socket.open(); socket.message(event('agent_message')); await first;
    const pending = stream.next().catch((error: unknown) => error);
    if (closeFirst) setTimeout(() => socket.drop(4029), 1000);
    socket.onerror?.();
    if (!closeFirst) setTimeout(() => socket.drop(4029), 1000);
    await vi.advanceTimersByTimeAsync(1000);
    const failure = await pending;
    expect(failure).toBeInstanceOf(ConnectionError);
    expect(isRetryableError(failure)).toBe(closeFirst);
    expect((failure as ConnectionError).code).toBe(closeFirst ? 'WS_CLOSE_4029' : undefined);
    expect(socket.close).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['debate_end', 'error'] as const)('lets genuine %s win during close observation', async (terminal) => {
    const off = vi.spyOn(AragoraWebSocket.prototype, 'off');
    const stream = streamDebate(config);
    const first = stream.next(); const socket = FakeSocket.latest;
    socket.open(); socket.message(event('agent_message')); await first;
    socket.message(event('agent_message', 'saved')); socket.onerror?.();
    await vi.advanceTimersByTimeAsync(500); socket.message(event(terminal));
    await vi.advanceTimersByTimeAsync(0); checkCleanup(socket, off);
    expect((await stream.next()).value).toEqual(event('agent_message', 'saved'));
    expect((await stream.next()).value).toEqual(event(terminal));
    await vi.advanceTimersByTimeAsync(1000);
    expect(await stream.next()).toEqual(done);
  });

  it('keeps constructor failures immediate rather than awaiting close', async () => {
    const failure = new Error('setup failed');
    vi.stubGlobal('WebSocket', class { constructor() { throw failure; } });
    await expect(streamDebate(config).next()).rejects.toBe(failure);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('preserves standalone callback errors and automatic reconnection', async () => {
    const socketClient = new AragoraWebSocket(config, { reconnectDelay: 10 });
    const errors = vi.fn(); socketClient.on('error', errors);
    const connect = socketClient.connect(); const socket = FakeSocket.latest;
    const rejected = expect(connect).rejects.toThrow('WebSocket error');
    socket.onerror?.(); await rejected;
    expect(errors).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
    socket.drop(); await vi.advanceTimersByTimeAsync(10);
    expect(FakeSocket.latest).not.toBe(socket);
    socketClient.disconnect(); expect(vi.getTimerCount()).toBe(0);
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
