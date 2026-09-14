import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createClient, type Debate } from '@aragora/sdk';
import { connectDebateStream, displayEvent } from '../app/debate-stream';
import { debateView, formatPercentage } from '../app/debate-view';

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

test('installed SDK numeric running rounds are requested, not completed rounds', async () => {
  const original = globalThis.fetch;
  try {
    // The running-debate handler returns a count, not the completed round array.
    for (const rounds of [0, 5]) {
      for (const rounds_used of [undefined, 2]) {
        globalThis.fetch = async () => new Response(JSON.stringify({
          ...debate, status: 'running', in_progress: true, rounds, rounds_used,
        }), { headers: { 'content-type': 'application/json' } });
        const value = await createClient({ baseUrl: 'https://api.example.test' })
          .debates.get(debate.debate_id);
        assert.equal(value.rounds, rounds);
        const view = debateView(value);
        assert.equal(view.roundsCompleted, rounds_used ?? 0);
        assert.deepEqual(view.messages, []);
      }
    }
  } finally {
    globalThis.fetch = original;
  }
});

test('installed SDK saved records retain top-level messages and their attribution', async () => {
  const original = globalThis.fetch;
  const messages = [
    { role: 'assistant', agent: 'reviewer', content: 'Saved proposal', round: 0 },
    { role: 'assistant', agent_id: 'peer', content: 'Saved dissent', round: 1 },
  ];
  try {
    for (const rounds of [undefined, 2, [], [{ round_number: 1, messages: [] }]]) {
      globalThis.fetch = async () => new Response(JSON.stringify({
        ...debate, rounds, rounds_used: 2, messages,
      }), { headers: { 'content-type': 'application/json' } });
      const value = await createClient({ baseUrl: 'https://api.example.test' })
        .debates.get(debate.debate_id);
      const view = debateView(value);
      assert.deepEqual(view.messages, messages);
      assert.equal(view.roundsCompleted, 2);
      assert.equal(view.messages[0].round, 0);
    }
  } finally {
    globalThis.fetch = original;
  }
});

test('round history is not duplicated by a saved-message fallback', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({
      ...debate,
      rounds: [{ round_number: 2, messages: [
        { role: 'assistant', agent: 'reviewer', content: 'Proposal' },
      ] }],
      messages: [{ role: 'assistant', agent: 'reviewer', content: 'Proposal', round: 2 }],
    }), { headers: { 'content-type': 'application/json' } });
    const value = await createClient({ baseUrl: 'https://api.example.test' })
      .debates.get(debate.debate_id);
    assert.deepEqual(debateView(value).messages, [
      { role: 'assistant', agent: 'reviewer', content: 'Proposal', round: 2 },
    ]);
  } finally {
    globalThis.fetch = original;
  }
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

test('event routing preserves SDK ID precedence and nested loop IDs', () => {
  const event = { type: 'agent_message' as const, timestamp: debate.created_at,
    data: { loop_id: debate.debate_id, content: 'Nested proposal' } };
  assert.equal(displayEvent(event, debate.debate_id)?.content, 'Nested proposal');
  assert.equal(displayEvent({ ...event, debate_id: 'other' }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, loop_id: 'other' }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, data: { ...event.data, debate_id: 'other' } }, debate.debate_id), null);
  assert.equal(displayEvent({ ...event, debate_id: '', loop_id: '' }, debate.debate_id)?.content, 'Nested proposal');
  assert.equal(displayEvent({ ...event, data: { loop_id: 42 } }, debate.debate_id), null);
});

test('server epoch seconds and top-level agent survive display conversion', () => {
  // StreamEvent.to_dict emits epoch seconds and agent outside the data envelope.
  const event = { type: 'agent_message' as const, loop_id: debate.debate_id,
    timestamp: Date.parse(debate.created_at) / 1000 + 0.5, agent: 'wire-reviewer',
    data: { content: 'Server proposal', agent: 'nested-reviewer' } };
  assert.deepEqual(displayEvent(event, debate.debate_id), {
    type: 'agent_message', timestamp: '2026-09-13T00:00:00.500Z',
    agent: 'wire-reviewer', content: 'Server proposal',
  });
  assert.equal(displayEvent({ ...event, timestamp: 0 }, debate.debate_id)?.timestamp, '1970-01-01T00:00:00.000Z');
  assert.equal(displayEvent({ ...event, timestamp: -1 }, debate.debate_id)?.timestamp, '1969-12-31T23:59:59.000Z');
  assert.equal(displayEvent({ ...event, timestamp: debate.created_at }, debate.debate_id)?.timestamp, debate.created_at);
  assert.equal(displayEvent({ ...event, agent: '' }, debate.debate_id)?.agent, 'nested-reviewer');
  assert.equal(displayEvent({ ...event, agent: { name: 'invalid' } }, debate.debate_id)?.agent, 'nested-reviewer');
});

test('invalid or missing time remains unknown while retaining the message', () => {
  const event = { type: 'agent_message' as const, loop_id: debate.debate_id,
    agent: 'wire-reviewer', data: { content: 'Keep this message' } };
  for (const timestamp of [undefined, null, Number.NaN, Infinity, Number.MAX_VALUE, '', 'not-a-date']) {
    const rendered = displayEvent({ ...event, timestamp }, debate.debate_id);
    assert.ok(rendered);
    assert.equal(rendered.timestamp, undefined);
    assert.equal(rendered.agent, 'wire-reviewer');
    assert.equal(rendered.content, 'Keep this message');
  }
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

for (const [name, frame, expectedError] of [
  ['server error', JSON.stringify({ type: 'error', data: {
    message: 'Permission denied: debates:read required', code: 403,
  } }), 'Permission denied: debates:read required'],
  ['malformed JSON', '{invalid', 'Failed to parse message: {invalid'],
  ['unknown error shape', JSON.stringify({ type: 'error', data: { code: 500 } }), 'Failed to connect'],
]) {
  test(`installed SDK ${name} preserves live connection and subsequent events`, async () => {
    const original = globalThis.WebSocket;
    let cleanup: (() => void) | undefined;
    try {
      globalThis.WebSocket = BrowserSocket as unknown as typeof WebSocket;
      const stream = createClient({ baseUrl: 'https://api.example.test' })
        .createWebSocket({ autoReconnect: false });
      const states: boolean[] = [];
      const errors: (string | null)[] = [];
      const messages: string[] = [];
      cleanup = connectDebateStream(stream, debate.debate_id, {
        onConnected: value => states.push(value), onError: value => errors.push(value),
        onEvent: value => messages.push(value.content ?? ''),
      });
      const socket = BrowserSocket.instances.at(-1)!;
      socket.onopen?.();
      await Promise.resolve();
      socket.onmessage?.({ data: frame });
      assert.equal(stream.getState(), 'connected');
      assert.equal(states.at(-1), true);
      assert.equal(errors.at(-1), expectedError);
      socket.onmessage?.({ data: JSON.stringify({ type: 'agent_message',
        loop_id: debate.debate_id, data: { content: 'Still live' } }) });
      assert.deepEqual(messages, ['Still live']);
      socket.onerror?.();
      assert.equal(states.at(-1), true);
      assert.equal(errors.at(-1), 'WebSocket error');
      socket.onclose?.({ code: 1006, reason: 'Connection lost' });
      assert.equal(states.at(-1), false);
      cleanup();
      const calls = [states.length, errors.length, messages.length];
      socket.onmessage?.({ data: frame });
      socket.onerror?.();
      await Promise.resolve();
      assert.deepEqual([states.length, errors.length, messages.length], calls);
    } finally {
      cleanup?.();
      globalThis.WebSocket = original;
    }
  });
}

test('initial connection rejection reports a disconnected error state', async () => {
  const original = globalThis.WebSocket;
  let cleanup: (() => void) | undefined;
  try {
    globalThis.WebSocket = BrowserSocket as unknown as typeof WebSocket;
    const stream = createClient({ baseUrl: 'https://api.example.test' })
      .createWebSocket({ autoReconnect: false });
    const states: boolean[] = [];
    const errors: (string | null)[] = [];
    cleanup = connectDebateStream(stream, debate.debate_id, {
      onConnected: value => states.push(value), onError: value => errors.push(value), onEvent: () => {},
    });
    BrowserSocket.instances.at(-1)!.onerror?.();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(states.at(-1), false);
    assert.ok(!states.includes(true));
    assert.equal(errors.at(-1), 'WebSocket error');
  } finally {
    cleanup?.();
    globalThis.WebSocket = original;
  }
});

test('installed SDK delivers the actual server envelope without losing time or attribution', async () => {
  const original = globalThis.WebSocket;
  const events: ReturnType<typeof displayEvent>[] = [];
  let cleanup: (() => void) | undefined;
  try {
    globalThis.WebSocket = BrowserSocket as unknown as typeof WebSocket;
    const stream = createClient({ baseUrl: 'https://api.example.test' })
      .createWebSocket({ autoReconnect: false });
    cleanup = connectDebateStream(stream, debate.debate_id, {
      onEvent: value => events.push(value), onConnected: () => {}, onError: () => {},
    });
    const socket = BrowserSocket.instances.at(-1)!;
    socket.onopen?.();
    socket.onmessage?.({ data: JSON.stringify({ type: 'agent_message',
      timestamp: 1789257600.5, agent: 'wire-reviewer', round: 0, seq: 0, agent_seq: 0,
      data: { loop_id: debate.debate_id, content: 'Actual wire proposal' } }) });
    assert.deepEqual(events, [{ type: 'agent_message',
      timestamp: '2026-09-13T00:00:00.500Z', agent: 'wire-reviewer', content: 'Actual wire proposal' }]);
    socket.onmessage?.({ data: JSON.stringify({ type: 'agent_message',
      timestamp: 1789257600.5, agent: 'other',
      data: { loop_id: 'other-debate', content: 'Excluded proposal' } }) });
    assert.equal(events.length, 1);
  } finally {
    cleanup?.();
    globalThis.WebSocket = original;
  }
});

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
