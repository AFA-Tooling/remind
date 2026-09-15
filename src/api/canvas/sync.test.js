import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './sync.js';

// Regression coverage: a sync request must only ever act on the verified
// caller's own account, never on an arbitrary email in the body.

function makeDb() {
  const updates = [];
  return {
    _updates: updates,
    collection(collection) {
      return {
        doc(id) {
          return {
            async update(value) { updates.push({ collection, id, value }); },
          };
        },
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

test('handler rejects with 401 when unauthorized, and never triggers a sync', async () => {
  let syncTouched = false;
  const deps = {
    verifyUserAuth: async () => ({ authorized: false, error: 'Missing authorization token' }),
    getDb: () => makeDb(),
    syncCanvasAssignments: async () => { syncTouched = true; return { synced: 0, removed: 0 }; },
  };
  const res = makeRes();
  await handler({ method: 'POST', body: { user_email: 'other-student@berkeley.edu' } }, res, deps);
  assert.equal(res.statusCode, 401);
  assert.equal(syncTouched, false, 'must reject before ever triggering a sync');
});

test('handler syncs the verified caller, not a claimed user_email in the body', async () => {
  let syncedEmail = null;
  const deps = {
    verifyUserAuth: async () => ({ authorized: true, email: 'real-user@berkeley.edu' }),
    getDb: () => makeDb(),
    syncCanvasAssignments: async (_db, email) => { syncedEmail = email; return { synced: 2, removed: 1 }; },
  };
  const res = makeRes();
  // Body claims to sync a different student entirely.
  await handler({ method: 'POST', body: { user_email: 'other-student@berkeley.edu' } }, res, deps);
  assert.equal(res.statusCode, 200);
  assert.equal(syncedEmail, 'real-user@berkeley.edu');
  assert.equal(res.body.synced, 2);
});

test('handler records the sync_error under the verified caller\'s email on failure', async () => {
  const db = makeDb();
  const deps = {
    verifyUserAuth: async () => ({ authorized: true, email: 'real-user@berkeley.edu' }),
    getDb: () => db,
    syncCanvasAssignments: async () => { throw new Error('Canvas is down'); },
  };
  const res = makeRes();
  await handler({ method: 'POST', body: { user_email: 'other-student@berkeley.edu' } }, res, deps);
  assert.equal(res.statusCode, 500);
  assert.equal(db._updates.length, 1);
  assert.equal(db._updates[0].id, 'real-user@berkeley.edu');
});
