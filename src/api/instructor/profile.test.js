import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './profile.js';

function makeRes() {
  const res = { statusCode: null, body: null };
  res.status = code => { res.statusCode = code; return res; };
  res.json = body => { res.body = body; return res; };
  return res;
}

function makeDb(role = 'instructor') {
  const profiles = new Map([['uid-1', { role }]]);
  return {
    collection(name) {
      assert.equal(name, 'user_profiles');
      return {
        doc(id) {
          return {
            async get() {
              const profile = profiles.get(id);
              return { exists: !!profile, data: () => profile };
            },
            async set(value, options = {}) {
              profiles.set(id, options.merge ? { ...profiles.get(id), ...value } : value);
            },
          };
        },
      };
    },
    _profiles: profiles,
  };
}

const authorized = async () => ({ authorized: true, uid: 'uid-1' });

test('instructor profile returns and saves preferred name', async () => {
  const db = makeDb();
  const saveRes = makeRes();
  await handler(
    { method: 'PUT', body: { preferred_first_name: '  Alex  ' } },
    saveRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(saveRes.statusCode, 200);
  assert.equal(saveRes.body.preferred_first_name, 'Alex');

  const getRes = makeRes();
  await handler(
    { method: 'GET' },
    getRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(getRes.statusCode, 200);
  assert.equal(getRes.body.preferred_first_name, 'Alex');
});

test('instructor profile rejects non-instructors and oversized names', async () => {
  const studentRes = makeRes();
  await handler(
    { method: 'PUT', body: { preferred_first_name: 'Alex' } },
    studentRes,
    { verifyUserAuth: authorized, getDb: () => makeDb('student') },
  );
  assert.equal(studentRes.statusCode, 403);

  const longNameRes = makeRes();
  await handler(
    { method: 'PUT', body: { preferred_first_name: 'a'.repeat(51) } },
    longNameRes,
    { verifyUserAuth: authorized, getDb: makeDb },
  );
  assert.equal(longNameRes.statusCode, 400);
});
