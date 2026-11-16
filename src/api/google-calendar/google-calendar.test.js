import test from 'node:test';
import assert from 'node:assert/strict';

import { createOAuthState, getOAuthStateId } from './googleClient.js';
import authHandler from './auth.js';
import callbackHandler from './callback.js';
import disconnectHandler from './disconnect.js';
import handler, { syncGoogleTasks } from './sync.js';

function makeDb() {
  const collections = new Map();
  const getCollection = (name) => {
    if (!collections.has(name)) collections.set(name, new Map());
    const records = collections.get(name);
    return {
      doc(id) {
        return {
          async get() {
            const data = records.get(id);
            return { exists: !!data, data: () => data };
          },
          async set(data) { records.set(id, { ...data }); },
          async update(data) {
            records.set(id, { ...records.get(id), ...data });
          },
          async delete() { records.delete(id); },
        };
      },
      where(field, operator, value) {
        assert.equal(operator, '==');
        return {
          async get() {
            const docs = [...records.entries()]
              .filter(([, data]) => data[field] === value)
              .map(([id, data]) => ({ id, data: () => data }));
            return { docs, empty: docs.length === 0 };
          },
        };
      },
    };
  };
  return { collection: getCollection };
}

const assignment = (due = '2026-10-30T00:00:00.000Z') => ({
  assignment_name: 'Homework 1',
  course_code: 'CS101',
  due,
  source: 'gradesync',
  completed: false,
});

test('OAuth state is opaque, unique, and stored by a one-way hash', () => {
  const first = createOAuthState();
  const second = createOAuthState();
  assert.notEqual(first, second);
  assert.equal(first.length, 43);
  assert.notEqual(getOAuthStateId(first), first);
  assert.equal(getOAuthStateId(first), getOAuthStateId(first));
});

test('OAuth initiation stores caller identity server-side and returns an authorization URL', async () => {
  const previous = {
    clientId: process.env.GOOGLE_CALENDAR_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CALENDAR_CLIENT_SECRET,
    redirectUri: process.env.GOOGLE_CALENDAR_REDIRECT_URI,
  };
  process.env.GOOGLE_CALENDAR_CLIENT_ID = 'client-id';
  process.env.GOOGLE_CALENDAR_CLIENT_SECRET = 'client-secret';
  process.env.GOOGLE_CALENDAR_REDIRECT_URI = 'https://example.com/api/google-calendar/callback';
  const stored = new Map();
  try {
    const res = makeRes();
    await authHandler({ method: 'POST', headers: { 'x-forwarded-proto': 'https' } }, res, {
      verifyUserAuth: async () => ({ authorized: true, email: 'student@example.com' }),
      getDb: () => ({
        collection(name) {
          assert.equal(name, 'google_calendar_oauth_states');
          return {
            doc(id) {
              return { async set(data) { stored.set(id, data); } };
            },
          };
        },
      }),
    });
    assert.equal(res.statusCode, 200);
    const authorizationUrl = new URL(res.body.authorization_url);
    const state = authorizationUrl.searchParams.get('state');
    assert.equal(authorizationUrl.origin, 'https://accounts.google.com');
    assert.equal(stored.get(getOAuthStateId(state)).email, 'student@example.com');
    assert.equal(state.includes('student@example.com'), false);
    assert.match(res.headers['Set-Cookie'], /HttpOnly/);
    assert.match(res.headers['Set-Cookie'], /SameSite=Lax/);
    assert.match(res.headers['Set-Cookie'], /Secure/);
    assert.match(res.headers['Set-Cookie'], /Path=\/api\/google-calendar\/callback/);
  } finally {
    if (previous.clientId === undefined) delete process.env.GOOGLE_CALENDAR_CLIENT_ID;
    else process.env.GOOGLE_CALENDAR_CLIENT_ID = previous.clientId;
    if (previous.clientSecret === undefined) delete process.env.GOOGLE_CALENDAR_CLIENT_SECRET;
    else process.env.GOOGLE_CALENDAR_CLIENT_SECRET = previous.clientSecret;
    if (previous.redirectUri === undefined) delete process.env.GOOGLE_CALENDAR_REDIRECT_URI;
    else process.env.GOOGLE_CALENDAR_REDIRECT_URI = previous.redirectUri;
  }
});

test('OAuth callback rejects a missing or mismatched state cookie before looking up state', async () => {
  const previous = {
    clientId: process.env.GOOGLE_CALENDAR_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CALENDAR_CLIENT_SECRET,
    redirectUri: process.env.GOOGLE_CALENDAR_REDIRECT_URI,
  };
  process.env.GOOGLE_CALENDAR_CLIENT_ID = 'client-id';
  process.env.GOOGLE_CALENDAR_CLIENT_SECRET = 'client-secret';
  process.env.GOOGLE_CALENDAR_REDIRECT_URI = 'http://localhost:3000/api/google-calendar/callback';
  let dbRequested = false;
  try {
    const state = createOAuthState();
    const res = makeRes();
    await callbackHandler({
      query: { state, code: 'authorization-code' },
      headers: { cookie: 'autore_google_oauth_state=another-state' },
    }, res, {
      getDb: () => { dbRequested = true; return makeDb(); },
      exchangeCodeForTokens: async () => { throw new Error('Token exchange must not run'); },
    });

    assert.equal(dbRequested, false);
    assert.equal(res.redirectUrl, '/index.html?calendar=error&reason=state_mismatch');
    assert.match(res.headers['Set-Cookie'], /autore_google_oauth_state=;/);
    assert.match(res.headers['Set-Cookie'], /Max-Age=0/);
    assert.doesNotMatch(res.headers['Set-Cookie'], /Secure/);
  } finally {
    if (previous.clientId === undefined) delete process.env.GOOGLE_CALENDAR_CLIENT_ID;
    else process.env.GOOGLE_CALENDAR_CLIENT_ID = previous.clientId;
    if (previous.clientSecret === undefined) delete process.env.GOOGLE_CALENDAR_CLIENT_SECRET;
    else process.env.GOOGLE_CALENDAR_CLIENT_SECRET = previous.clientSecret;
    if (previous.redirectUri === undefined) delete process.env.GOOGLE_CALENDAR_REDIRECT_URI;
    else process.env.GOOGLE_CALENDAR_REDIRECT_URI = previous.redirectUri;
  }
});

test('OAuth callback accepts matching cookie state, exchanges code, and clears cookie', async () => {
  const previous = {
    clientId: process.env.GOOGLE_CALENDAR_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CALENDAR_CLIENT_SECRET,
    redirectUri: process.env.GOOGLE_CALENDAR_REDIRECT_URI,
  };
  process.env.GOOGLE_CALENDAR_CLIENT_ID = 'client-id';
  process.env.GOOGLE_CALENDAR_CLIENT_SECRET = 'client-secret';
  process.env.GOOGLE_CALENDAR_REDIRECT_URI = 'http://localhost:3000/api/google-calendar/callback';
  try {
    const state = createOAuthState();
    const db = makeDb();
    await db.collection('google_calendar_oauth_states').doc(getOAuthStateId(state)).set({
      email: 'student@example.com',
      created_at: new Date().toISOString(),
    });
    const res = makeRes();
    let exchangedCode;
    await callbackHandler({
      query: { state, code: 'authorization-code' },
      headers: { cookie: `autore_google_oauth_state=${state}` },
    }, res, {
      getDb: () => db,
      exchangeCodeForTokens: async (code) => {
        exchangedCode = code;
        return { access_token: 'access-token', refresh_token: 'refresh-token', expires_in: 3600 };
      },
    });

    assert.equal(exchangedCode, 'authorization-code');
    assert.equal(res.redirectUrl, '/index.html?calendar=connected');
    assert.match(res.headers['Set-Cookie'], /Max-Age=0/);
    assert.equal((await db.collection('google_calendar_tokens').doc('student@example.com').get()).data().refresh_token, 'refresh-token');
    assert.equal((await db.collection('google_calendar_oauth_states').doc(getOAuthStateId(state)).get()).exists, false);
  } finally {
    if (previous.clientId === undefined) delete process.env.GOOGLE_CALENDAR_CLIENT_ID;
    else process.env.GOOGLE_CALENDAR_CLIENT_ID = previous.clientId;
    if (previous.clientSecret === undefined) delete process.env.GOOGLE_CALENDAR_CLIENT_SECRET;
    else process.env.GOOGLE_CALENDAR_CLIENT_SECRET = previous.clientSecret;
    if (previous.redirectUri === undefined) delete process.env.GOOGLE_CALENDAR_REDIRECT_URI;
    else process.env.GOOGLE_CALENDAR_REDIRECT_URI = previous.redirectUri;
  }
});

test('sync creates tasks once, skips unchanged tasks, and updates changed due dates', async () => {
  const db = makeDb();
  const calls = [];
  const syncedAssignment = {
    ...assignment(),
    html_url: 'https://example.com/homework-1',
  };
  let newTaskId = 0;
  const deps = {
    getAccessToken: async () => ({
      accessToken: 'access-token',
      tokenData: { task_list_id: 'task-list' },
      ref: { async update() {} },
    }),
    tasksRequest: async (_token, method, path, body) => {
      calls.push({ method, path, body });
      if (method === 'POST') return { id: `task-${++newTaskId}` };
      if (method === 'PATCH') return { id: 'task-1' };
      throw new Error(`Unexpected request: ${method} ${path}`);
    },
  };

  assert.deepEqual(await syncGoogleTasks(db, 'student@example.com', [syncedAssignment], deps), {
    created: 1, updated: 0, unchanged: 0, skippedWithoutDueDate: 0,
  });
  assert.deepEqual(await syncGoogleTasks(db, 'student@example.com', [syncedAssignment], deps), {
    created: 0, updated: 0, unchanged: 1, skippedWithoutDueDate: 0,
  });
  assert.deepEqual(await syncGoogleTasks(db, 'student@example.com', [{
    ...syncedAssignment,
    due: '2026-11-02',
  }], deps), {
    created: 0, updated: 1, unchanged: 0, skippedWithoutDueDate: 0,
  });
  assert.deepEqual(await syncGoogleTasks(db, 'student@example.com', [{
    ...syncedAssignment,
    due: '2026-11-02',
    assignment_name: 'Homework 2',
  }], deps), {
    created: 0, updated: 1, unchanged: 0, skippedWithoutDueDate: 0,
  });
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(calls.filter(call => call.method === 'PATCH').length, 2);
  assert.equal(calls[0].body.status, 'needsAction');
  for (const update of calls.filter(call => call.method === 'PATCH')) {
    assert.equal('status' in update.body, false);
    assert.equal('completed' in update.body, false);
  }
  assert.equal(calls[1].body.due, '2026-11-02T00:00:00.000Z');
  assert.equal(calls[2].body.title, 'Homework 2 (CS101)');
});

test('sync preserves the assignment due date from timestamps with timezone offsets', async () => {
  const calls = [];
  await syncGoogleTasks(makeDb(), 'student@example.com', [
    assignment('2026-11-09T23:59:59-08:00'),
  ], {
    getAccessToken: async () => ({
      accessToken: 'access-token',
      tokenData: { task_list_id: 'task-list' },
      ref: { async update() {} },
    }),
    tasksRequest: async (_token, method, _path, body) => {
      calls.push({ method, body });
      return { id: 'task-1' };
    },
  });
  assert.equal(calls.find(call => call.method === 'POST').body.due, '2026-11-09T00:00:00.000Z');
});

test('sync derives the due date in Los Angeles time for timestamps near UTC midnight', async () => {
  const calls = [];
  await syncGoogleTasks(makeDb(), 'student@example.com', [
    { ...assignment('2026-11-10T00:30:00.000Z'), assignment_name: 'Late night assignment' },
  ], {
    getAccessToken: async () => ({
      accessToken: 'access-token',
      tokenData: { task_list_id: 'task-list' },
      ref: { async update() {} },
    }),
    tasksRequest: async (_token, method, _path, body) => {
      if (method === 'GET') return { items: [] };
      calls.push({ method, body });
      return { id: 'task-1' };
    },
  });
  assert.equal(calls.find(call => call.method === 'POST').body.due, '2026-11-09T00:00:00.000Z');
});

test('sync leaves date-only due dates unchanged in Los Angeles time', async () => {
  const calls = [];
  await syncGoogleTasks(makeDb(), 'student@example.com', [
    { ...assignment('2026-11-09'), assignment_name: 'Date-only assignment' },
  ], {
    getAccessToken: async () => ({
      accessToken: 'access-token',
      tokenData: { task_list_id: 'task-list' },
      ref: { async update() {} },
    }),
    tasksRequest: async (_token, method, _path, body) => {
      if (method === 'GET') return { items: [] };
      calls.push({ method, body });
      return { id: 'task-1' };
    },
  });
  assert.equal(calls.find(call => call.method === 'POST').body.due, '2026-11-09T00:00:00.000Z');
});

test('sync skips assignments without due dates', async () => {
  const result = await syncGoogleTasks(makeDb(), 'student@example.com', [assignment(null)], {
    getAccessToken: async () => ({
      accessToken: 'access-token',
      tokenData: { task_list_id: 'task-list' },
      ref: { async update() {} },
    }),
    tasksRequest: async () => { throw new Error('No task should be sent without a due date'); },
  });
  assert.deepEqual(result, { created: 0, updated: 0, unchanged: 0, skippedWithoutDueDate: 1 });
});

function makeRes() {
  return {
    statusCode: null,
    body: null,
    headers: {},
    redirectUrl: null,
    status(code) { this.statusCode = code; return this; },
    json(data) { this.body = data; return this; },
    setHeader(name, value) { this.headers[name] = value; return this; },
    redirect(_code, url) { this.redirectUrl = url; return this; },
  };
}

test('sync endpoint rejects unauthorized and malformed requests before calling Google', async () => {
  let dbRequested = false;
  const deps = {
    verifyUserAuth: async () => ({ authorized: false, error: 'Invalid token' }),
    getDb: () => { dbRequested = true; return makeDb(); },
    tasksRequest: async () => { throw new Error('Google must not be called'); },
  };
  const unauthorized = makeRes();
  await handler({ method: 'POST', body: { assignments: [assignment()] } }, unauthorized, deps);
  assert.equal(unauthorized.statusCode, 401);
  assert.equal(dbRequested, false);

  const authorizedDeps = { ...deps, verifyUserAuth: async () => ({ authorized: true, email: 'student@example.com' }) };
  const invalid = makeRes();
  await handler({ method: 'POST', body: { assignments: [{ ...assignment(), source: 'other' }] } }, invalid, authorizedDeps);
  assert.equal(invalid.statusCode, 400);
  assert.equal(dbRequested, false);
});

test('disconnect revokes the refresh token before deleting the local token record', async () => {
  const operations = [];
  const res = makeRes();
  await disconnectHandler({ method: 'POST' }, res, {
    verifyUserAuth: async () => ({ authorized: true, email: 'student@example.com' }),
    getDb: () => ({
      collection(name) {
        assert.equal(name, 'google_calendar_tokens');
        return {
          doc(email) {
            assert.equal(email, 'student@example.com');
            return {
              async get() {
                return {
                  exists: true,
                  data: () => ({ access_token: 'access-token', refresh_token: 'refresh-token' }),
                };
              },
              async delete() { operations.push('delete'); },
            };
          },
        };
      },
    }),
    revokeToken: async token => { operations.push(`revoke:${token}`); },
  });
  assert.equal(res.statusCode, 200);
  assert.deepEqual(operations, ['revoke:refresh-token', 'delete']);
});
