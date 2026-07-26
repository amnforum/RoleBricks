import { randomUUID } from 'node:crypto';

const TOKEN_REFRESH_SKEW_MS = 60_000;
const UPSTREAM_TIMEOUT_MS = 285_000;
const MAX_BODY_BYTES = 4_000_000;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SAFE_REQUEST_HEADERS = [
  'accept',
  'accept-language',
  'content-type',
  'if-modified-since',
  'if-none-match',
  'range'
];
const SAFE_RESPONSE_HEADERS = [
  'accept-ranges',
  'content-disposition',
  'content-range',
  'content-type',
  'etag',
  'last-modified'
];

let cachedToken = null;
let tokenRequest = null;
const rateBuckets = new Map();

class GatewayError extends Error {
  constructor(status, publicMessage, code, retryAfter = null) {
    super(publicMessage);
    this.status = status;
    this.publicMessage = publicMessage;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

function sendJson(response, status, payload, extraHeaders = {}) {
  response.statusCode = status;
  response.setHeader('content-type', 'application/json; charset=utf-8');
  response.setHeader('cache-control', 'no-store');
  for (const [name, value] of Object.entries(extraHeaders)) response.setHeader(name, value);
  response.end(JSON.stringify(payload));
}

function requiredConfig() {
  const values = {
    host: process.env.DATABRICKS_HOST,
    appUrl: process.env.DATABRICKS_APP_URL,
    clientId: process.env.DATABRICKS_CLIENT_ID,
    clientSecret: process.env.DATABRICKS_CLIENT_SECRET
  };
  if (Object.values(values).some((value) => !value?.trim())) {
    throw new GatewayError(503, 'The public gateway is not configured yet.', 'gateway_not_configured');
  }
  return {
    ...values,
    host: httpsOrigin(values.host, 'DATABRICKS_HOST'),
    appUrl: httpsOrigin(values.appUrl, 'DATABRICKS_APP_URL')
  };
}

function httpsOrigin(value, label) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new GatewayError(503, 'The public gateway is not configured yet.', `${label}_invalid`);
  }
  if (parsed.protocol !== 'https:') {
    throw new GatewayError(503, 'The public gateway is not configured yet.', `${label}_not_https`);
  }
  return parsed.origin;
}

function oneQueryValue(value) {
  if (Array.isArray(value)) return value[0] || '';
  return typeof value === 'string' ? value : '';
}

function routeFor(resourceValue, methodValue) {
  const resource = oneQueryValue(resourceValue).replace(/^\/+|\/+$/g, '');
  const method = String(methodValue || 'GET').toUpperCase();
  if (!resource || resource.includes('..') || resource.includes('\\') || !/^[a-z0-9/_-]+$/i.test(resource)) {
    throw new GatewayError(404, 'Not found.', 'route_not_found');
  }

  const effectiveMethod = method === 'HEAD' ? 'GET' : method;
  const parts = resource.split('/');
  let allowedMethod = null;
  let privateCollection = false;
  let quota = 'general';

  if (resource === 'ready') {
    allowedMethod = 'GET';
  } else if (resource === 'transcribe') {
    allowedMethod = 'POST';
    quota = 'expensive';
  } else if (resource === 'worlds') {
    allowedMethod = 'GET';
    privateCollection = true;
  } else if (resource === 'worlds/draft') {
    allowedMethod = 'POST';
    quota = 'expensive';
  } else if (parts[0] === 'worlds' && UUID_PATTERN.test(parts[1] || '')) {
    if (parts.length === 2) allowedMethod = method === 'DELETE' ? 'DELETE' : 'GET';
    if (parts.length === 3 && parts[2] === 'blueprint') allowedMethod = 'PATCH';
    if (parts.length === 3 && ['history', 'memories'].includes(parts[2])) allowedMethod = 'DELETE';
    if (parts.length === 3 && ['revert', 'enter', 'pause', 'resume', 'complete'].includes(parts[2])) {
      allowedMethod = 'POST';
    }
    if (parts.length === 3 && parts[2] === 'confirm') {
      allowedMethod = 'POST';
      quota = 'expensive';
    }
    if (parts.length === 3 && parts[2] === 'turns') {
      allowedMethod = 'POST';
      quota = 'dialogue';
    }
    if (
      parts.length === 5 &&
      parts[2] === 'turns' &&
      UUID_PATTERN.test(parts[3]) &&
      parts[4] === 'audio'
    ) allowedMethod = 'GET';
    if (
      parts.length === 5 &&
      parts[2] === 'agents' &&
      UUID_PATTERN.test(parts[3]) &&
      parts[4] === 'sample'
    ) allowedMethod = 'GET';
    if (
      parts.length === 4 &&
      parts[2] === 'sources' &&
      UUID_PATTERN.test(parts[3])
    ) allowedMethod = 'DELETE';
  }

  if (!allowedMethod) throw new GatewayError(404, 'Not found.', 'route_not_found');
  if (effectiveMethod !== allowedMethod) {
    throw new GatewayError(405, 'Method not allowed.', 'method_not_allowed');
  }
  return { resource, method, privateCollection, quota, allowedMethod };
}

function clientAddress(request) {
  const forwarded = oneQueryValue(request.headers?.['x-forwarded-for']);
  return forwarded.split(',')[0]?.trim() || request.headers?.['x-real-ip'] || 'unknown';
}

function enforceRateLimit(request, quota) {
  const now = Date.now();
  const limits = {
    general: { max: 240, windowMs: 60_000 },
    dialogue: { max: 60, windowMs: 600_000 },
    expensive: { max: 15, windowMs: 600_000 }
  };
  const limit = limits[quota];
  const key = `${clientAddress(request)}:${quota}`;
  let bucket = rateBuckets.get(key);
  if (!bucket || bucket.expiresAt <= now) {
    bucket = { count: 0, expiresAt: now + limit.windowMs };
    rateBuckets.set(key, bucket);
  }
  bucket.count += 1;
  if (bucket.count > limit.max) {
    const retryAfter = Math.max(1, Math.ceil((bucket.expiresAt - now) / 1000));
    throw new GatewayError(429, 'Too many requests. Please wait a moment and try again.', 'rate_limited', retryAfter);
  }
  if (rateBuckets.size > 5000) {
    for (const [bucketKey, value] of rateBuckets) {
      if (value.expiresAt <= now) rateBuckets.delete(bucketKey);
    }
  }
}

async function accessToken(config) {
  const now = Date.now();
  if (cachedToken && cachedToken.expiresAt - TOKEN_REFRESH_SKEW_MS > now) return cachedToken.value;
  if (tokenRequest) return tokenRequest;

  tokenRequest = (async () => {
    const credentials = Buffer.from(`${config.clientId}:${config.clientSecret}`, 'utf8').toString('base64');
    const result = await fetch(`${config.host}/oidc/v1/token`, {
      method: 'POST',
      headers: {
        authorization: `Basic ${credentials}`,
        'content-type': 'application/x-www-form-urlencoded'
      },
      body: new URLSearchParams({ grant_type: 'client_credentials', scope: 'all-apis' }),
      redirect: 'manual'
    });
    if (!result.ok) {
      throw new GatewayError(503, 'Databricks authentication is temporarily unavailable.', 'oauth_failed');
    }
    const payload = await result.json();
    if (!payload.access_token || !Number(payload.expires_in)) {
      throw new GatewayError(503, 'Databricks authentication is temporarily unavailable.', 'oauth_invalid');
    }
    cachedToken = {
      value: payload.access_token,
      expiresAt: Date.now() + Number(payload.expires_in) * 1000
    };
    return cachedToken.value;
  })();

  try {
    return await tokenRequest;
  } finally {
    tokenRequest = null;
  }
}

async function readRequestBody(request) {
  if (['GET', 'HEAD'].includes(String(request.method).toUpperCase())) return undefined;
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_BODY_BYTES) {
      throw new GatewayError(413, 'The upload is too large for the public demo.', 'body_too_large');
    }
    chunks.push(buffer);
  }
  return chunks.length ? Buffer.concat(chunks) : undefined;
}

function upstreamUrl(config, route, query = {}) {
  const url = new URL(`/api/${route.resource}`, config.appUrl);
  for (const [key, rawValue] of Object.entries(query)) {
    if (key === 'resource') continue;
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) {
      if (value !== undefined && value !== null) url.searchParams.append(key, String(value));
    }
  }
  return url;
}

function upstreamHeaders(request, token, requestId) {
  const headers = new Headers({
    authorization: `Bearer ${token}`,
    'x-rolebricks-request-id': requestId
  });
  for (const name of SAFE_REQUEST_HEADERS) {
    const value = request.headers?.[name];
    if (typeof value === 'string' && value) headers.set(name, value);
  }
  return headers;
}

async function proxyRequest(request, response, route, requestId) {
  if (route.privateCollection) {
    sendJson(response, 200, []);
    return;
  }

  const config = requiredConfig();
  const token = await accessToken(config);
  const body = await readRequestBody(request);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  timeout.unref?.();

  let upstream;
  try {
    upstream = await fetch(upstreamUrl(config, route, request.query), {
      method: route.method,
      headers: upstreamHeaders(request, token, requestId),
      body,
      redirect: 'manual',
      signal: controller.signal
    });
  } finally {
    clearTimeout(timeout);
  }

  if (upstream.status >= 300 && upstream.status < 400) {
    throw new GatewayError(502, 'The scene service returned an unexpected sign-in response.', 'upstream_redirect');
  }

  response.statusCode = upstream.status;
  response.setHeader('cache-control', 'no-store');
  response.setHeader('x-rolebricks-request-id', requestId);
  for (const name of SAFE_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) response.setHeader(name, value);
  }
  if (route.method === 'HEAD' || !upstream.body) {
    response.end();
    return;
  }
  response.end(Buffer.from(await upstream.arrayBuffer()));
}

export default async function handler(request, response) {
  const requestId = randomUUID();
  try {
    if (request.method === 'OPTIONS') {
      response.statusCode = 204;
      response.setHeader('allow', 'GET, HEAD, POST, PATCH, DELETE, OPTIONS');
      response.end();
      return;
    }
    const route = routeFor(request.query?.resource, request.method);
    enforceRateLimit(request, 'general');
    if (route.quota !== 'general') enforceRateLimit(request, route.quota);
    await proxyRequest(request, response, route, requestId);
  } catch (error) {
    if (error instanceof GatewayError) {
      const headers = error.retryAfter ? { 'retry-after': String(error.retryAfter) } : {};
      sendJson(response, error.status, { error: error.publicMessage, request_id: requestId }, headers);
      return;
    }
    const timedOut = error?.name === 'AbortError';
    console.error(`[rolebricks-gateway:${requestId}] ${timedOut ? 'upstream_timeout' : 'upstream_failure'}`);
    sendJson(
      response,
      timedOut ? 504 : 502,
      { error: timedOut ? 'The scene service timed out.' : 'The scene service is temporarily unavailable.', request_id: requestId }
    );
  }
}

export const config = {
  api: {
    bodyParser: false
  }
};

export function resetGatewayStateForTests() {
  cachedToken = null;
  tokenRequest = null;
  rateBuckets.clear();
}
