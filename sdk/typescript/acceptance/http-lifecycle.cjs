// Native installed-bundle acceptance: node <this file> <isolated consumer directory>
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { createRequire } = require('node:module');
const { pathToFileURL } = require('node:url');
const { createHash } = require('node:crypto');
const consumer = fs.realpathSync(process.argv[2]);
const selectedMode = process.argv[3];
assert(!selectedMode || ['CJS', 'ESM'].includes(selectedMode), 'optional mode must be CJS or ESM');
const installed = createRequire(path.join(consumer, 'package.json'));
const cjs = fs.realpathSync(installed.resolve('@aragora/sdk'));
const esm = fs.realpathSync(path.join(path.dirname(cjs), 'index.mjs'));
for (const entry of [cjs, esm]) {
  const relative = path.relative(path.join(consumer, 'node_modules'), entry);
  assert(relative && !relative.startsWith('..') && !path.isAbsolute(relative), entry);
}
const snippets = [...fs.readFileSync(path.join(__dirname, '../REQUEST_LIFECYCLE.md'), 'utf8')
  .matchAll(/```typescript\n([\s\S]*?)```/g)].map(match => match[1]);
assert.equal(snippets.length, 2);
const probeDirectory = fs.mkdtempSync(path.join(consumer, 'acceptance-'));
const probe = path.join(probeDirectory, 'probe.mjs');
fs.writeFileSync(probe, "import * as sdk from '@aragora/sdk';\nexport { sdk };\nexport const entry = import.meta.resolve('@aragora/sdk');\n");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const original = { fetch: global.fetch, set: global.setTimeout, clear: global.clearTimeout };
let cases = 0;

async function deterministic(sdk) {
  const timers = new Map();
  let sequence = 0;
  global.setTimeout = (callback, delay) => {
    const id = ++sequence;
    timers.set(id, { callback, delay });
    return id;
  };
  global.clearTimeout = id => timers.delete(id);
  const fire = id => {
    const timer = timers.get(id);
    assert(timer, 'attempt deadline still owned');
    timers.delete(id);
    timer.callback();
  };
  const client = new sdk.AragoraClient({ baseUrl: 'http://127.0.0.1:1', maxRetries: 3, timeout: 900 });
  const sleeps = [];
  client.sleep = async delay => {
    assert.equal(timers.size, 0, 'release attempt timer before backoff');
    sleeps.push(delay);
  };
  const operations = [
    [() => client.debates.create({ task: 'fixture' }), '/api/debate', 'POST'],
    [() => client.codeReview.reviewCode({ code: 'return 1' }), '/api/v1/code-review/review', 'POST'],
    [() => client.receipts.getV2('example'), '/api/v2/receipts/example', 'GET'],
  ];
  try {
    for (const [invoke, route, method] of operations) {
      for (const kind of ['invalid', 'body', 'json', 'empty']) {
        const calls = [];
        const failure = new TypeError('network body failure');
        global.fetch = async (url, init) => {
          calls.push([new URL(url).pathname, init.method]);
          const response = new Response(kind === 'json' ? '{"ok":true}' : kind === 'empty' ? '' : '{invalid');
          if (kind === 'body') response.text = async () => { throw failure; };
          return response;
        };
        if (kind === 'invalid') await assert.rejects(invoke(), SyntaxError);
        else if (kind === 'body') await assert.rejects(invoke(), error => error === failure);
        else assert.deepEqual(await invoke(), kind === 'json' ? { ok: true } : {});
        assert.deepEqual(calls, [[route, method]]);
        assert.equal(timers.size, 0); assert.deepEqual(sleeps, []); cases++;
      }
    }
    for (const [body, status, responseType, expected] of [
      [null, 204, 'json', {}], ['{invalid', 200, 'text', '{invalid'], ['', 200, 'text', ''],
    ]) {
      global.fetch = async () => new Response(body, { status });
      assert.deepEqual(await client.request('POST', '/fixture', { responseType }), expected);
      assert.equal(timers.size, 0); cases++;
    }
    let calls = 0;
    global.fetch = async () => { calls++; throw new TypeError('fetch failed'); };
    await assert.rejects(client.get('/fixture'), sdk.ConnectionError);
    assert.equal(calls, 1); assert.equal(timers.size, 0); cases++;
    calls = 0;
    global.fetch = async () => new Response(++calls === 1 ? '{}' : '{invalid', { status: calls === 1 ? 503 : 200 });
    await assert.rejects(client.post('/fixture', {}), SyntaxError);
    assert.equal(calls, 2); assert.deepEqual(sleeps.splice(0), [1000]);
    assert.equal(timers.size, 0); cases++;

    for (const phase of ['headers', 'body']) {
      for (const status of [200, 400, 503]) {
        for (const prior of [false, true]) {
          calls = 0;
          let entered;
          const ready = new Promise(resolve => { entered = resolve; });
          global.fetch = async (_url, init) => {
            if (++calls === 1 && prior) return new Response('{}', { status: 503 });
            const pending = () => new Promise((_resolve, reject) => {
              init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true });
              entered();
            });
            return phase === 'headers' ? pending() : { ok: status === 200, status, text: pending, json: pending };
          };
          const outcome = assert.rejects(client.request('POST', '/fixture', { timeout: 37 }), error => {
            assert(error instanceof sdk.TimeoutError);
            assert.equal(error.message, phase === 'body' ? 'Response body timeout' : 'Request timeout');
            assert.equal(error.code, 'SERVICE_UNAVAILABLE');
            return true;
          });
          await ready;
          assert.equal(timers.size, 1);
          const [id, timer] = [...timers][0];
          assert.equal(timer.delay, 37, 'per-request deadline override');
          fire(id); await outcome;
          assert.equal(calls, prior ? 2 : 1); assert.equal(timers.size, 0);
          assert.deepEqual(sleeps.splice(0), prior ? [1000] : []); cases++;
        }
      }
    }
    // Independent concurrent bodies: one completion cannot cancel the other's deadline.
    const bodies = [];
    let entered;
    const ready = new Promise(resolve => { entered = resolve; });
    global.fetch = async (_url, init) => ({
      ok: true, text: () => new Promise((resolve, reject) => {
        bodies.push(resolve);
        init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true });
        if (bodies.length === 2) entered();
      }),
    });
    const first = client.get('/first');
    const second = assert.rejects(client.get('/second'), sdk.TimeoutError);
    await ready;
    const ids = [...timers.keys()];
    bodies[0]('{"ok":true}'); assert.deepEqual(await first, { ok: true });
    assert(!timers.has(ids[0])); assert.equal(timers.size, 1);
    fire(ids[1]); bodies[1]('{"late":true}'); await second;
    assert.equal(timers.size, 0); cases++;

    for (const phase of ['headers', 'body']) {
      let entered;
      const ready = new Promise(resolve => { entered = resolve; });
      const messages = [];
      calls = 0;
      global.fetch = async (_url, init) => {
        calls++;
        const pending = () => new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true });
          entered();
        });
        return phase === 'headers' ? pending() : { ok: true, text: pending };
      };
      const code = snippets[1].replace("import { TimeoutError } from '@aragora/sdk';", '');
      const example = new AsyncFunction('client', 'TimeoutError', 'console', code)(
        client, sdk.TimeoutError, { error: message => messages.push(message) },
      );
      await ready; fire([...timers.keys()][0]); await example;
      assert.deepEqual(messages, [phase === 'body'
        ? 'Response interrupted; inspect operation state before retrying.'
        : 'Request failed; server-side outcome may still be unknown.']);
      assert.equal(calls, 1); assert.equal(timers.size, 0); cases++;
    }
    for (const valid of [false, true]) {
      calls = 0; const messages = [];
      global.fetch = async () => { calls++; return new Response(valid ? '{}' : '{invalid'); };
      await new AsyncFunction('client', 'console', snippets[0])(client, {
        log: () => messages.push('success'), error: () => messages.push('failure'),
      });
      assert.deepEqual(messages, [valid ? 'success' : 'failure']);
      assert.equal(calls, 1); assert.equal(timers.size, 0); cases++;
    }
  } finally {
    global.fetch = original.fetch; global.setTimeout = original.set; global.clearTimeout = original.clear;
  }
}

async function loopback(sdk) {
  for (const scenario of ['healthy', 'invalid', 'headers', 200, 400, 503]) {
    let received = 0;
    const server = http.createServer((request, response) => {
      received++; request.resume();
      if (scenario === 'headers') return;
      response.writeHead(typeof scenario === 'number' ? scenario : 200, { 'content-type': 'application/json' });
      if (typeof scenario === 'number') response.write('{"pending":');
      else response.end(scenario === 'invalid' ? '{invalid' : '{"ok":true}');
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const client = new sdk.AragoraClient({
      baseUrl: `http://127.0.0.1:${server.address().port}`, timeout: 200, maxRetries: 3,
    });
    const start = performance.now();
    const watchdog = original.set(() => server.closeAllConnections(), 3000);
    try {
      if (scenario === 'healthy') assert.deepEqual(await client.debates.create({ task: 'fixture' }), { ok: true });
      else if (scenario === 'invalid') await assert.rejects(client.debates.create({ task: 'fixture' }), SyntaxError);
      else {
        await assert.rejects(client.debates.create({ task: 'fixture' }), error => {
          assert(error instanceof sdk.TimeoutError);
          assert.equal(error.message, scenario === 'headers' ? 'Request timeout' : 'Response body timeout');
          return true;
        });
      }
      assert(performance.now() - start < 2500, 'deadline must beat the watchdog');
      assert.equal(received, 1); cases++;
    } finally {
      original.clear(watchdog); server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    }
  }
}

// A broken abort/cleanup implementation must fail, not silently exit with a pending Promise.
const watchdog = original.set(() => {
  console.error('Installed acceptance exceeded its 30-second watchdog'); process.exit(1);
}, 30_000);
(async () => {
  for (const [mode, entry] of [['CJS', cjs], ['ESM', esm]]) {
    if (selectedMode && mode !== selectedMode) continue;
    const resolved = mode === 'ESM' ? await import(pathToFileURL(probe).href) : null;
    if (resolved) assert.equal(resolved.entry, pathToFileURL(esm).href, 'native import export condition');
    const sdk = resolved ? resolved.sdk : installed('@aragora/sdk');
    await deterministic(sdk); await loopback(sdk);
    console.log(JSON.stringify({ mode, entry, sha256: createHash('sha256').update(fs.readFileSync(entry)).digest('hex'),
      node: process.version, cumulativeCases: cases }));
  }
  console.log(JSON.stringify({ pass: true, cases }));
})().catch(error => { console.error(error); process.exitCode = 1; })
  .finally(() => {
    original.clear(watchdog); fs.unlinkSync(probe); fs.rmdirSync(probeDirectory);
  });
