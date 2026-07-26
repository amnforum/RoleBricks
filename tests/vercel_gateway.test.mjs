import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import test from 'node:test';

import handler, { resetGatewayStateForTests } from '../api/gateway.js';

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };

function configureGateway() {
  process.env.DATABRICKS_HOST = 'https://workspace.example.com';
  process.env.DATABRICKS_APP_URL = 'https://rolebricks.example.com';
  process.env.DATABRICKS_CLIENT_ID = 'client-id';
  process.env.DATABRICKS_CLIENT_SECRET = 'client-secret';
}

function mockResponse() {
  const headers = new Map();
  return {
    statusCode: 200,
    body: Buffer.alloc(0),
    setHeader(name, value) {
      headers.set(String(name).toLowerCase(), String(value));
    },
    getHeader(name) {
      return headers.get(String(name).toLowerCase());
    },
    end(value) {
      if (value !== undefined) this.body = Buffer.isBuffer(value) ? value : Buffer.from(String(value));
    }
  };
}

async function invoke({ method = 'GET', resource, headers = {}, body } = {}) {
  const request = Readable.from(body === undefined ? [] : [Buffer.from(body)]);
  request.method = method;
  request.query = { resource };
  request.headers = headers;
  const response = mockResponse();
  await handler(request, response);
  return response;
}

function jsonBody(response) {
  return JSON.parse(response.body.toString('utf8'));
}

test.beforeEach(() => {
  resetGatewayStateForTests();
  configureGateway();
});

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test.after(() => {
  process.env = originalEnv;
});

test('proxies an allowlisted API route and reuses the short-lived OAuth token', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    if (String(url).endsWith('/oidc/v1/token')) {
      return new Response(JSON.stringify({ access_token: 'short-lived-token', expires_in: 3600 }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      });
    }
    return new Response(JSON.stringify({ ready: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  };

  const first = await invoke({ resource: 'ready' });
  const second = await invoke({ resource: 'ready' });

  assert.equal(first.statusCode, 200);
  assert.deepEqual(jsonBody(first), { ready: true });
  assert.equal(second.statusCode, 200);
  assert.equal(calls.filter((call) => call.url.endsWith('/oidc/v1/token')).length, 1);
  const upstreamCalls = calls.filter((call) => call.url.includes('rolebricks.example.com/api/ready'));
  assert.equal(upstreamCalls.length, 2);
  assert.equal(upstreamCalls[0].options.headers.get('authorization'), 'Bearer short-lived-token');
});

test('forwards raw JSON bodies without forwarding browser credentials', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), options });
    if (String(url).endsWith('/oidc/v1/token')) {
      return new Response(JSON.stringify({ access_token: 'token', expires_in: 3600 }));
    }
    return new Response(JSON.stringify({ id: 'created' }), {
      status: 201,
      headers: { 'content-type': 'application/json' }
    });
  };

  const payload = JSON.stringify({ prompt: 'A realistic practice interview tomorrow.' });
  const response = await invoke({
    method: 'POST',
    resource: 'worlds/draft',
    body: payload,
    headers: {
      'content-type': 'application/json',
      authorization: 'Browser secret that must not pass through',
      cookie: 'private=true'
    }
  });

  assert.equal(response.statusCode, 201);
  const upstream = calls.at(-1);
  assert.equal(Buffer.from(upstream.options.body).toString('utf8'), payload);
  assert.equal(upstream.options.headers.get('authorization'), 'Bearer token');
  assert.equal(upstream.options.headers.has('cookie'), false);
});

test('keeps the global scene collection private while allowing browser-local recent scenes', async () => {
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount += 1;
    throw new Error('The upstream should not be called');
  };

  const response = await invoke({ resource: 'worlds' });

  assert.equal(response.statusCode, 200);
  assert.deepEqual(jsonBody(response), []);
  assert.equal(fetchCount, 0);
});

test('rejects admin and unknown routes before authentication', async () => {
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount += 1;
    throw new Error('The upstream should not be called');
  };

  const response = await invoke({ resource: 'admin/overview' });

  assert.equal(response.statusCode, 404);
  assert.equal(jsonBody(response).error, 'Not found.');
  assert.equal(fetchCount, 0);
});

test('fails closed when server-only credentials are missing', async () => {
  delete process.env.DATABRICKS_CLIENT_SECRET;
  const response = await invoke({ resource: 'ready' });

  assert.equal(response.statusCode, 503);
  assert.equal(jsonBody(response).error, 'The public gateway is not configured yet.');
});
