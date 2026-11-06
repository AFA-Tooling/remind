import test from 'node:test';
import assert from 'node:assert/strict';

import { createOAuthState, getOAuthStateId } from './googleClient.js';
import authHandler from './auth.js';
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
    await authHandler({ method: 'POST' }, res, {
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

  assert.deepEqual(await syncGoogleTasks(db, 'student@example.com', [assignment()], deps), {
    created: 1, updated: 0, unchanged: 0, skippedWithoutDueDate: 0,
  });
  assert.deepEqual(await syncGoogleTasks(db, 'student@example.com', [assignment()], deps), {
    created: 0, updated: 0, unchanged: 1, skippedWithoutDueDate: 0,
  });
  assert.deepEqual(await syncGoogleTasks(db, 'student@example.com', [assignment('2026-11-02')], deps), {
    created: 0, updated: 1, unchanged: 0, skippedWithoutDueDate: 0,
  });
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(calls.filter(call => call.method === 'PATCH').length, 1);
  assert.equal(calls.at(-1).body.due, '2026-11-02T00:00:00.000Z');
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
  assert.equal(calls[0].body.due, '2026-11-09T00:00:00.000Z');
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
    status(code) { this.statusCode = code; return this; },
    json(data) { this.body = data; return this; },
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
