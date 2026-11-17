import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './role.js';

function makeRes() {
  const res = { statusCode: null, body: null };
  res.status = (code) => { res.statusCode = code; return res; };
  res.json = (data) => { res.body = data; return res; };
  return res;
}

function makeDb(existing = null) {
  let profile = existing;
  let documentId;
  const db = {
    collection(name) {
      assert.equal(name, 'user_profiles');
      return {
        doc(id) {
          documentId = id;
          return {
            async get() {
              return { exists: profile !== null, data: () => profile };
            },
            async set(value) {
              profile = { ...profile, ...value };
            },
          };
        },
      };
    },
  };
  return { db, get profile() { return profile; }, get documentId() { return documentId; } };
}

const authorized = async () => ({
  authorized: true,
  uid: 'firebase-uid',
  email: 'user@example.edu',
});

test('GET returns null for a user without a saved role', async () => {
  const store = makeDb();
  const res = makeRes();
  await handler({ method: 'GET' }, res, { verifyUserAuth: authorized, getDb: () => store.db });
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.role, null);
  assert.equal(store.documentId, 'firebase-uid');
});

test('PUT stores a validated role under the authenticated user ID', async () => {
  const store = makeDb();
  const res = makeRes();
  await handler(
    { method: 'PUT', body: { role: 'instructor' } },
    res,
    { verifyUserAuth: authorized, getDb: () => store.db },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(store.documentId, 'firebase-uid');
  assert.equal(store.profile.role, 'instructor');
  assert.equal(store.profile.email, 'user@example.edu');
  assert.ok(store.profile.created_at);
  assert.ok(store.profile.updated_at);
});

test('PUT rejects unsupported roles without writing', async () => {
  const store = makeDb();
  const res = makeRes();
  await handler(
    { method: 'PUT', body: { role: 'admin' } },
    res,
    { verifyUserAuth: authorized, getDb: () => store.db },
  );
  assert.equal(res.statusCode, 400);
  assert.equal(store.profile, null);
});

test('PUT rejects malformed JSON', async () => {
  const store = makeDb();
  const res = makeRes();
  await handler(
    { method: 'PUT', body: '{' },
    res,
    { verifyUserAuth: authorized, getDb: () => store.db },
  );
  assert.equal(res.statusCode, 400);
  assert.equal(store.profile, null);
});

test('handler rejects unauthenticated requests', async () => {
  const res = makeRes();
  await handler(
    { method: 'GET' },
    res,
    { verifyUserAuth: async () => ({ authorized: false, error: 'Missing token' }) },
  );
  assert.equal(res.statusCode, 401);
});

test('handler rejects unsupported methods', async () => {
  const res = makeRes();
  await handler({ method: 'DELETE' }, res, { verifyUserAuth: authorized });
  assert.equal(res.statusCode, 405);
});
