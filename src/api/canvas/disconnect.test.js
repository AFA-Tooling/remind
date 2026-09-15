import test from 'node:test';
import assert from 'node:assert/strict';

import handler, { disconnectCanvas } from './disconnect.js';

// Regression coverage: a disconnect request must only ever affect the
// verified caller's own account, never an arbitrary email in the body.

function makeDb(seed = {}) {
  const data = new Map();
  for (const [collection, docs] of Object.entries(seed)) {
    for (const [id, value] of Object.entries(docs)) data.set(`${collection}/${id}`, value);
  }
  const deleted = [];

  return {
    _data: data,
    _deleted: deleted,
    collection(collection) {
      return {
        doc(id) {
          const key = `${collection}/${id}`;
          return {
            async delete() { deleted.push(key); data.delete(key); },
            async set(value, options) {
              data.set(key, options?.merge ? { ...(data.get(key) || {}), ...value } : value);
            },
          };
        },
        where(field, op, value) {
          const docs = [...data.entries()]
            .filter(([k]) => k.startsWith(`${collection}/`))
            .filter(([, v]) => v[field] === value)
            .map(([k, v]) => ({ ref: { delete: () => { deleted.push(k); data.delete(k); } } }));
          return { async get() { return { docs, empty: docs.length === 0 }; } };
        },
      };
    },
    batch() {
      const ops = [];
      return {
        delete(ref) { ops.push(ref); },
        async commit() { for (const ref of ops) ref.delete(); },
      };
    },
  };
}

function makeRes() {
  const res = { statusCode: null, body: null };
  res.status = (code) => { res.statusCode = code; return res; };
  res.json = (data) => { res.body = data; return res; };
  return res;
}

test('disconnectCanvas deletes only the given email\'s token, deadlines, and flag', async () => {
  const db = makeDb({
    canvas_tokens: { 'other-student@berkeley.edu': { access_token: 'real' } },
    canvas_deadlines: { d1: { email: 'other-student@berkeley.edu', assignment_name: 'X' } },
    students: { 'other-student@berkeley.edu': { canvas_connected: true } },
  });
  await disconnectCanvas(db, 'other-student@berkeley.edu');
  assert.equal(db._data.has('canvas_tokens/other-student@berkeley.edu'), false);
  assert.equal(db._data.has('canvas_deadlines/d1'), false);
  assert.equal(db._data.get('students/other-student@berkeley.edu').canvas_connected, false);
});

test('handler rejects with 401 when unauthorized, and never touches the database', async () => {
  let dbTouched = false;
  const deps = {
    verifyUserAuth: async () => ({ authorized: false, error: 'Missing authorization token' }),
    getDb: () => { dbTouched = true; return makeDb(); },
  };
  const res = makeRes();
  await handler({ method: 'POST', body: { user_email: 'other-student@berkeley.edu' } }, res, deps);
  assert.equal(res.statusCode, 401);
  assert.equal(dbTouched, false, 'must reject before ever reaching the database');
});

test('handler disconnects the verified caller, not a claimed user_email in the body', async () => {
  const db = makeDb({
    canvas_tokens: {
      'caller@berkeley.edu': { access_token: 'callers own' },
      'other-student@berkeley.edu': { access_token: 'other students real token' },
    },
    students: {
      'caller@berkeley.edu': { canvas_connected: true },
      'other-student@berkeley.edu': { canvas_connected: true },
    },
  });
  const deps = {
    verifyUserAuth: async () => ({ authorized: true, email: 'caller@berkeley.edu' }),
    getDb: () => db,
  };
  const res = makeRes();
  // Body claims to disconnect a different student entirely.
  await handler({ method: 'POST', body: { user_email: 'other-student@berkeley.edu' } }, res, deps);
  assert.equal(res.statusCode, 200);
  assert.equal(db._data.has('canvas_tokens/caller@berkeley.edu'), false, 'the caller\'s own token is removed');
  assert.equal(db._data.has('canvas_tokens/other-student@berkeley.edu'), true, 'the other student\'s token must survive');
});
