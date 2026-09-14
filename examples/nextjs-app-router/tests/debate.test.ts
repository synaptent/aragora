import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createClient, type Debate } from '@aragora/sdk';
import { connectDebateStream, displayEvent } from '../lib/debate-stream';
import { debateView, formatPercentage } from '../lib/debate-view';

const debate: Debate = {
  debate_id: 'debate-1', task: 'Compare proposals', status: 'completed',
  created_at: '2026-09-13T00:00:00Z', agents: ['reviewer'],
};

test('missing consensus data is not presented as a measured zero', () => {
  assert.equal(formatPercentage(undefined), 'Not reported');
  assert.equal(formatPercentage(Number.NaN), 'Not reported');
  assert.equal(formatPercentage(0), '0.0%');
  assert.equal(debateView(debate).confidence, 'Not reported');
  assert.equal(debateView(debate).agreement, 'Not reported');
  assert.deepEqual(debateView(debate).messages, []);
});

test('published consensus fields, rounds and message attribution are preserved', () => {
  const view = debateView({
    ...debate,
    rounds_used: 3,
    rounds: [{ round_number: 2, messages: [
      { role: 'assistant', agent: 'reviewer', content: 'Reasoning' },
      { role: 'assistant', agent_id: 'peer', content: 'Dissent', round: 1 },
    ] }],
    consensus: { reached: false, confidence: 0, agreement: 0.5, conclusion: 'Not settled' },
  });
  assert.equal(view.roundsCompleted, 3);
  assert.equal(view.confidence, '0.0%');
  assert.equal(view.agreement, '50.0%');
  assert.equal(view.answer, 'Not settled');
  assert.deepEqual(view.messages.map(message => message.round), [2, 1]);
  assert.equal(view.messages[1].agent_id, 'peer');
});

test('answer and round fallbacks use only SDK fields', () => {
  assert.equal(debateView({ ...debate, final_answer: 'Final' }).answer, 'Final');
  assert.equal(debateView({ ...debate, final_answer: 'Final', consensus: {
    reached: true, final_answer: 'Consensus', conclusion: 'Conclusion',
  } }).answer, 'Consensus');
  assert.equal(debateView({ ...debate, rounds: [{ round_number: 1, messages: [] }] }).roundsCompleted, 1);
});

test('event envelopes retain data and reject other debates and global messages', () => {
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

test('nested loop IDs follow published SDK precedence and reject malformed IDs', () => {
  const event = { type: 'agent_message' as const, timestamp: debate.created_at,
    data: { loop_id: debate.debate_id, content: 'Nested loop message' } };
  assert.equal(displayEvent(event, debate.debate_id)?.content, 'Nested loop message');
  assert.equal(displayEvent({ ...event, debate_id: 'other' }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, loop_id: 'other' }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, data: { ...event.data, debate_id: 'other' } }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, debate_id: '', data: {
    ...event.data, debate_id: '',
  } }, debate.debate_id)?.content, 'Nested loop message');
  assert.equal(displayEvent({ ...event, data: {
    ...event.data, debate_id: 123,
  } }, debate.debate_id)?.content, 'Nested loop message');
  assert.equal(displayEvent({ ...event, data: { loop_id: 123 } }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, data: { loop_id: 'other' } }, debate.debate_id), null);
});

test('server wire timestamps use seconds and top-level agent attribution wins', () => {
  const event = { type: 'agent_message' as const, timestamp: 1789000000.5,
    agent: 'wire-reviewer', loop_id: debate.debate_id,
    data: { agent: 'nested-reviewer', content: 'Wire proposal' } };
  assert.deepEqual(displayEvent(event, debate.debate_id), {
    type: 'agent_message', timestamp: '2026-09-10T00:26:40.500Z',
    agent: 'wire-reviewer', content: 'Wire proposal',
  });
  assert.equal(displayEvent({ ...event, timestamp: 0 }, debate.debate_id)?.timestamp,
    '1970-01-01T00:00:00.000Z');
  assert.equal(displayEvent({ ...event, timestamp: debate.created_at }, debate.debate_id)?.timestamp,
    debate.created_at);
  assert.equal(displayEvent({ ...event, agent: '' }, debate.debate_id)?.agent, 'nested-reviewer');
  assert.equal(displayEvent({ ...event, timestamp: Number.NaN }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, timestamp: Number.MAX_VALUE }, debate.debate_id), null);
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

test('published SDK preserves server timestamp and agent through message delivery', () => {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = BrowserSocket as unknown as typeof WebSocket;
  const messages: unknown[] = [];
  const stream = createClient({ baseUrl: 'https://example.test' }).createWebSocket({ autoReconnect: false });
  const cleanup = connectDebateStream(stream, debate.debate_id, {
    onConnected: () => {}, onError: () => {}, onEvent: event => messages.push(event),
  });
  const socket = BrowserSocket.instances.at(-1)!;
  try {
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'agent_message',
      timestamp: 1789000000.5, agent: 'wire-reviewer', loop_id: debate.debate_id,
      data: { content: 'Actual wire shape' } }) });
    assert.deepEqual(messages, [{ type: 'agent_message',
      timestamp: '2026-09-10T00:26:40.500Z', agent: 'wire-reviewer', content: 'Actual wire shape' }]);
  } finally {
    cleanup();
    globalThis.WebSocket = original;
  }
});

test('published SDK connection subscribes, projects messages, and cleans up on unmount', async () => {
  const original = globalThis.WebSocket;
  globalThis.WebSocket = BrowserSocket as unknown as typeof WebSocket;
  const states: boolean[] = [];
  const errors: (string | null)[] = [];
  const messages: string[] = [];
  const stream = createClient({ baseUrl: 'https://example.test' }).createWebSocket({ autoReconnect: false });
  const cleanup = connectDebateStream(stream, debate.debate_id, {
    onConnected: value => states.push(value), onError: value => errors.push(value),
    onEvent: value => messages.push(value.content ?? ''),
  });
  const socket = BrowserSocket.instances.at(-1)!;
  try {
    assert.equal(socket.url, 'wss://example.test/ws?debate_id=debate-1');
    socket.onopen?.();
    assert.deepEqual(states, [true]);
    assert.deepEqual(JSON.parse(socket.sent[0]), { type: 'subscribe', debate_id: debate.debate_id });
    socket.onmessage?.({ data: JSON.stringify({ type: 'agent_message', loop_id: debate.debate_id,
      timestamp: debate.created_at, data: { content: 'Streamed proposal' } }) });
    socket.onmessage?.({ data: JSON.stringify({ type: 'agent_message',
      timestamp: debate.created_at, data: { loop_id: debate.debate_id, content: 'Nested loop message' } }) });
    assert.deepEqual(messages, ['Streamed proposal', 'Nested loop message']);
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
    assert.equal(messages.length, 2);
  } finally {
    cleanup();
    globalThis.WebSocket = original;
  }
});

test('unmount during connection ignores late failures and releases a late open', async () => {
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
