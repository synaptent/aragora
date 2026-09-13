import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createClient, type Debate } from '@aragora/sdk';
import { connectDebateStream, displayEvent } from '../src/lib/debate-stream';
import { debateView, formatPercentage } from '../src/lib/debate-view';

const debate: Debate = {
  debate_id: 'debate-1', task: 'Compare proposals', status: 'completed',
  created_at: '2026-09-13T00:00:00Z', agents: ['reviewer'],
};

test('missing metrics do not become measured zeros', () => {
  assert.equal(formatPercentage(undefined), 'Not reported');
  assert.equal(formatPercentage(Number.NaN), 'Not reported');
  assert.equal(formatPercentage(0), '0.0%');
  assert.equal(debateView(debate).confidence, 'Not reported');
  assert.equal(debateView(debate).agreement, 'Not reported');
  assert.deepEqual(debateView(debate).messages, []);
});

test('published consensus, rounds and message attribution are retained', () => {
  const view = debateView({ ...debate, rounds_used: 3,
    consensus: { reached: false, confidence: 0, agreement: 0.5, conclusion: 'Not settled' },
    rounds: [{ round_number: 2, messages: [
      { role: 'assistant', agent: 'reviewer', content: 'Reasoning' },
      { role: 'assistant', agent_id: 'peer', content: 'Dissent', round: 1 },
    ] }],
  });
  assert.equal(view.roundsCompleted, 3);
  assert.equal(view.confidence, '0.0%');
  assert.equal(view.agreement, '50.0%');
  assert.equal(view.answer, 'Not settled');
  assert.deepEqual(view.messages.map(message => message.round), [2, 1]);
  assert.equal(view.messages[1].agent_id, 'peer');
});

test('answer and round fallbacks use only the published SDK fields', () => {
  assert.equal(debateView({ ...debate, final_answer: 'Final' }).answer, 'Final');
  assert.equal(debateView({ ...debate, final_answer: 'Final', consensus: {
    reached: true, final_answer: 'Consensus', conclusion: 'Conclusion',
  } }).answer, 'Consensus');
  assert.equal(debateView({ ...debate, rounds: [{ round_number: 1, messages: [] }] }).roundsCompleted, 1);
});

test('events use their data envelope and exclude other debates and global messages', () => {
  const event = { type: 'agent_message' as const, timestamp: debate.created_at,
    data: { agent: 'reviewer', content: 'Proposal' }, loop_id: debate.debate_id };
  assert.deepEqual(displayEvent(event, debate.debate_id), {
    type: 'agent_message', timestamp: debate.created_at, agent: 'reviewer', content: 'Proposal',
  });
  assert.equal(displayEvent({ ...event, debate_id: 'other' }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, loop_id: undefined }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, data: null }, debate.debate_id)?.content, undefined);
  assert.equal(displayEvent({ ...event, loop_id: undefined, data: {
    debate_id: debate.debate_id, content: 'Nested',
  } }, debate.debate_id)?.content, 'Nested');
});

class BrowserSocket {
  static instances: BrowserSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  sent: string[] = [];
  closed = false;
  constructor(public url: string) { BrowserSocket.instances.push(this); }
  send(data: string) { this.sent.push(data); }
  close() { this.closed = true; }
}

test('installed SDK uses configured backend, subscribes, reconnects and releases listeners', async () => {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = BrowserSocket as unknown as typeof WebSocket;
  const states: boolean[] = [];
  const errors: (string | null)[] = [];
  const messages: string[] = [];
  const stream = createClient({ baseUrl: 'https://api.example.test',
    wsUrl: 'wss://stream.example.test/ws' }).createWebSocket({ autoReconnect: false });
  const cleanup = connectDebateStream(stream, debate.debate_id, {
    onConnected: value => states.push(value), onError: value => errors.push(value),
    onEvent: value => messages.push(value.content ?? ''),
  });
  const socket = BrowserSocket.instances.at(-1)!;
  try {
    assert.equal(socket.url, 'wss://stream.example.test/ws?debate_id=debate-1');
    socket.onopen?.();
    assert.deepEqual(states, [true]);
    assert.deepEqual(JSON.parse(socket.sent[0]), { type: 'subscribe', debate_id: debate.debate_id });
    socket.onmessage?.({ data: JSON.stringify({ type: 'agent_message', loop_id: debate.debate_id,
      timestamp: debate.created_at, data: { content: 'Streamed proposal' } }) });
    assert.deepEqual(messages, ['Streamed proposal']);
    socket.onerror?.();
    assert.deepEqual(errors, [null, 'WebSocket error']);
    socket.onclose?.({ code: 1006, reason: 'Lost connection' });
    socket.onopen?.();
    assert.equal(socket.sent.length, 2);
    assert.equal(errors.at(-1), null);
    cleanup();
    cleanup();
    assert.equal(socket.closed, true);
    const stateCount = states.length;
    socket.onmessage?.({ data: JSON.stringify({ type: 'debate_end', debate_id: debate.debate_id }) });
    socket.onerror?.();
    await Promise.resolve();
    assert.equal(states.length, stateCount);
    assert.equal(messages.length, 1);
  } finally {
    cleanup();
    globalThis.WebSocket = original;
  }
});

test('unmount during connection ignores late failures and releases late opens', async () => {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = BrowserSocket as unknown as typeof WebSocket;
  const calls: unknown[] = [];
  const stream = createClient({ baseUrl: 'https://example.test' }).createWebSocket({ autoReconnect: false });
  const cleanup = connectDebateStream(stream, 'next-debate', {
    onConnected: value => calls.push(value), onError: value => calls.push(value), onEvent: value => calls.push(value),
  });
  const socket = BrowserSocket.instances.at(-1)!;
  try {
    cleanup();
    assert.equal(socket.closed, true);
    socket.onopen?.();
    socket.onerror?.();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(calls, []);
    assert.equal(stream.getState(), 'disconnected');
    assert.deepEqual(socket.sent, []);
  } finally {
    stream.disconnect();
    globalThis.WebSocket = original;
  }
});
