import test from 'node:test';
import assert from 'node:assert/strict';

import handler, { fetchCanvasDeadlines } from './deadlines.js';

// Regression coverage: the returned deadlines must come from the verified
// caller's own account, never from an arbitrary query param.

function makeDb(canvasDeadlines = []) {
  return {
    collection(name) {
      assert.equal(name, 'canvas_deadlines');
      return {
        where(field, op, value) {
          assert.equal(field, 'email');
          assert.equal(op, '==');
          const docs = canvasDeadlines
            .filter(d => d.email === value)
            .map(d => ({ data: () => d }));
          return { async get() { return { docs }; } };
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

test('fetchCanvasDeadlines returns only the given email\'s deadlines, sorted by due date', async () => {
  const db = makeDb([
    { email: 'a@berkeley.edu', assignment_name: 'Later', due: '2026-09-20T00:00:00' },
    { email: 'a@berkeley.edu', assignment_name: 'Earlier', due: '2026-09-05T00:00:00' },
    { email: 'b@berkeley.edu', assignment_name: 'Not mine', due: '2026-09-01T00:00:00' },
  ]);
  const result = await fetchCanvasDeadlines(db, 'a@berkeley.edu');
  assert.deepEqual(result.map(d => d.assignment_name), ['Earlier', 'Later']);
});

test('handler rejects with 401 when unauthorized, and never touches the database', async () => {
  let dbTouched = false;
  const deps = {
    verifyUserAuth: async () => ({ authorized: false, error: 'Missing authorization token' }),
    getDb: () => { dbTouched = true; return makeDb(); },
  };
  const res = makeRes();
  await handler({ method: 'GET', query: { user_email: 'other-student@berkeley.edu' } }, res, deps);
  assert.equal(res.statusCode, 401);
  assert.equal(dbTouched, false, 'must reject before ever reaching the database');
});

test('handler uses the verified email, not a claimed user_email query param', async () => {
  const db = makeDb([
    { email: 'real-user@berkeley.edu', assignment_name: 'Mine', due: '2026-09-10T00:00:00' },
    { email: 'other-student@berkeley.edu', assignment_name: 'Not mine', due: '2026-09-10T00:00:00' },
  ]);
  const deps = {
    verifyUserAuth: async () => ({ authorized: true, email: 'real-user@berkeley.edu' }),
    getDb: () => db,
  };
  const res = makeRes();
  // Query string claims to be a different student entirely.
  await handler({ method: 'GET', query: { user_email: 'other-student@berkeley.edu' } }, res, deps);
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.data.length, 1);
  assert.equal(res.body.data[0].assignment_name, 'Mine');
});
