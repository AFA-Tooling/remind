import test from 'node:test';
import assert from 'node:assert/strict';

import handler, { connectCanvasPat } from './pat.js';

// Regression coverage: a PAT must only ever be linked to the verified
// caller's own account — validating that the token itself is real isn't
// enough on its own, it also has to be saved under the right email.

function makeDb(seed = {}) {
  const data = new Map();
  for (const [collection, docs] of Object.entries(seed)) {
    for (const [id, value] of Object.entries(docs)) data.set(`${collection}/${id}`, value);
  }
  return {
    _data: data,
    collection(collection) {
      return {
        doc(id) {
          const key = `${collection}/${id}`;
          return {
            async set(value, options) {
              data.set(key, options?.merge ? { ...(data.get(key) || {}), ...value } : value);
            },
            async update(value) {
              data.set(key, { ...(data.get(key) || {}), ...value });
            },
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

test('connectCanvasPat saves the token and syncs under the given email', async () => {
  const db = makeDb();
  const canvasFetch = async () => ({ id: 999 }); // PAT validates fine
  const syncCanvasAssignments = async (_db, email) => ({ synced: 3, removed: 0, forEmail: email });

  const result = await connectCanvasPat(db, 'real-user@berkeley.edu', 'a-real-pat', { canvasFetch, syncCanvasAssignments });

  assert.equal(result.synced, 3);
  assert.equal(db._data.get('canvas_tokens/real-user@berkeley.edu').access_token, 'a-real-pat');
  assert.equal(db._data.get('students/real-user@berkeley.edu').canvas_connected, true);
});

test('connectCanvasPat still saves the token even when the initial sync fails', async () => {
  const db = makeDb();
  const canvasFetch = async () => ({ id: 999 });
  const syncCanvasAssignments = async () => { throw new Error('Canvas is down'); };

  const result = await connectCanvasPat(db, 'real-user@berkeley.edu', 'a-real-pat', { canvasFetch, syncCanvasAssignments });

  assert.equal(result.sync_warning, 'Canvas is down');
  assert.ok(db._data.has('canvas_tokens/real-user@berkeley.edu'), 'the token must still be saved');
});

test('connectCanvasPat saves nothing when the PAT itself is invalid', async () => {
  const db = makeDb();
  const canvasFetch = async () => { throw new Error('401 from Canvas'); };
  const syncCanvasAssignments = async () => { throw new Error('should never be called'); };

  await assert.rejects(
    () => connectCanvasPat(db, 'real-user@berkeley.edu', 'bad-pat', { canvasFetch, syncCanvasAssignments }),
    /401 from Canvas/
  );
  assert.equal(db._data.has('canvas_tokens/real-user@berkeley.edu'), false);
});

test('handler rejects with 401 when unauthorized, and never validates the PAT', async () => {
  let canvasTouched = false;
  const deps = {
    verifyUserAuth: async () => ({ authorized: false, error: 'Missing authorization token' }),
    getDb: () => makeDb(),
    canvasFetch: async () => { canvasTouched = true; return {}; },
    syncCanvasAssignments: async () => ({ synced: 0, removed: 0 }),
  };
  const res = makeRes();
  await handler({ method: 'POST', body: { user_email: 'other-student@berkeley.edu', pat: 'callers-real-pat' } }, res, deps);
  assert.equal(res.statusCode, 401);
  assert.equal(canvasTouched, false, 'must reject before ever validating a PAT');
});

test('handler links the PAT to the verified caller, not a claimed user_email in the body', async () => {
  const db = makeDb();
  const deps = {
    verifyUserAuth: async () => ({ authorized: true, email: 'caller@berkeley.edu' }),
    getDb: () => db,
    canvasFetch: async () => ({ id: 1 }),
    syncCanvasAssignments: async () => ({ synced: 1, removed: 0 }),
  };
  const res = makeRes();
  // Body claims to connect on behalf of a different student entirely.
  await handler({ method: 'POST', body: { user_email: 'other-student@berkeley.edu', pat: 'callers-real-pat' } }, res, deps);
  assert.equal(res.statusCode, 200);
  assert.equal(db._data.get('canvas_tokens/caller@berkeley.edu').access_token, 'callers-real-pat');
  assert.equal(db._data.has('canvas_tokens/other-student@berkeley.edu'), false, 'the other student must be untouched');
});
