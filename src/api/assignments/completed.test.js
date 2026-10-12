import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './completed.js';

function makeDb() {
  const data = new Map();

  function collection(path) {
    return {
      doc(id) {
        const docPath = `${path}/${id}`;
        return {
          async set(value) { data.set(docPath, value); },
          async delete() { data.delete(docPath); },
          collection(name) { return collection(docPath + '/' + name); },
        };
      },
      async get() {
        const prefix = path + '/';
        const docs = [...data.entries()]
          .filter(([docPath]) => docPath.startsWith(prefix) && !docPath.slice(prefix.length).includes('/'))
          .map(([, value]) => ({ data: () => value }));
        return { docs };
      },
    };
  }

  return { collection, _data: data };
}

function makeRes() {
  return {
    statusCode: null,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(body) { this.body = body; return this; },
  };
}

test('rejects unauthenticated requests before accessing Firestore', async () => {
  let dbTouched = false;
  const res = makeRes();
  await handler({ method: 'GET' }, res, {
    verifyUserAuth: async () => ({ authorized: false, error: 'Missing authorization token' }),
    getDb: () => { dbTouched = true; return makeDb(); },
  });

  assert.equal(res.statusCode, 401);
  assert.equal(dbTouched, false);
});

test('saves, lists, and removes completion for the verified user only', async () => {
  const db = makeDb();
  const deps = {
    verifyUserAuth: async () => ({ authorized: true, email: 'caller@berkeley.edu' }),
    getDb: () => db,
  };
  const assignmentKey = 'Project 1|CS101|2026-10-10|gradesync';

  const saveRes = makeRes();
  await handler({ method: 'POST', body: { assignment_key: assignmentKey, completed: true, user_email: 'other@berkeley.edu' } }, saveRes, deps);
  assert.equal(saveRes.statusCode, 200);
  assert.equal([...db._data.keys()].some(path => path.startsWith('students/caller@berkeley.edu/completed_assignments/')), true);
  assert.equal([...db._data.keys()].some(path => path.startsWith('students/other@berkeley.edu/')), false);

  const getRes = makeRes();
  await handler({ method: 'GET' }, getRes, deps);
  assert.deepEqual(getRes.body.data, [assignmentKey]);

  const removeRes = makeRes();
  await handler({ method: 'POST', body: { assignment_key: assignmentKey, completed: false } }, removeRes, deps);
  assert.equal(removeRes.statusCode, 200);

  const emptyRes = makeRes();
  await handler({ method: 'GET' }, emptyRes, deps);
  assert.deepEqual(emptyRes.body.data, []);
});

test('rejects invalid completion payloads', async () => {
  const res = makeRes();
  await handler({ method: 'POST', body: { assignment_key: '', completed: true } }, res, {
    verifyUserAuth: async () => ({ authorized: true, email: 'caller@berkeley.edu' }),
    getDb: makeDb,
  });

  assert.equal(res.statusCode, 400);
});