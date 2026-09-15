import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './get.js';

// Regression coverage for two bugs found together on 2026-09-15:
// 1. "Lab 2", "Midterm 1", etc. exist in multiple courses — without a
//    course_code filter, every course's same-named assignment's resources
//    got mixed into one list (e.g. CS61A's "Higher-Order Functions" reading
//    showing up under CS61C's "Lab 2").
// 2. Some assignment_resources docs are placeholder shells with no `link`
//    (e.g. exams that were never given a curated resource) — these rendered
//    as a broken "Resource: Link" pointing nowhere instead of being skipped.

function makeDb(docs) {
  return {
    collection(name) {
      assert.equal(name, 'assignment_resources');
      let filtered = docs;
      const query = {
        where(field, op, value) {
          assert.equal(op, '==');
          filtered = filtered.filter(d => d[field] === value);
          return query;
        },
        async get() {
          return { docs: filtered.map(d => ({ id: d.id, data: () => d })) };
        },
      };
      return query;
    },
  };
}

function makeRes() {
  const res = { statusCode: null, body: null };
  res.status = (code) => { res.statusCode = code; return res; };
  res.json = (data) => { res.body = data; return res; };
  return res;
}

// Mirrors the real 'Lab 2' data found in production: 3 real CS61A
// resources, 3 real CS61C resources, plus one empty CS61C placeholder.
const LAB_2_DOCS = [
  { id: 'a1', assignment_name: 'Lab 2', course_code: 'CS61A', resource_name: 'Reading - Ch 1.6: Higher-Order Functions', link: 'https://composingprograms.com/...' },
  { id: 'a2', assignment_name: 'Lab 2', course_code: 'CS61A', resource_name: 'Assignment Link', link: 'https://cs61a.org/...' },
  { id: 'a3', assignment_name: 'Lab 2', course_code: 'CS61A', resource_name: 'Videos - Lec 4', link: 'https://youtube.com/...' },
  { id: 'c1', assignment_name: 'Lab 2', course_code: 'CS61C', resource_name: 'Assignment Link', link: 'https://cs61c.org/...' },
  { id: 'c2', assignment_name: 'Lab 2', course_code: 'CS61C', resource_name: 'Reading - L05 Notes: C Memory Management', link: 'https://notes.cs61c.org/...' },
  { id: 'c3', assignment_name: 'Lab 2', course_code: 'CS61C' }, // placeholder shell, no link
];

test('with course_code, only that course\'s Lab 2 resources come back', async () => {
  const db = makeDb(LAB_2_DOCS);
  const res = makeRes();
  await handler({ method: 'GET', query: { assignment_name: 'Lab 2', course_code: 'CS61C' } }, res, { getDb: () => db });
  assert.equal(res.body.data.length, 2, 'the CS61C placeholder with no link should be dropped, leaving the 2 real ones');
  assert.ok(res.body.data.every(r => r.course_code === 'CS61C'));
  assert.ok(!res.body.data.some(r => r.resource_name?.includes('Higher-Order')), 'no CS61A content should leak in');
});

test('without course_code, every course\'s same-named resources come back (legacy behavior for callers that don\'t pass it)', async () => {
  const db = makeDb(LAB_2_DOCS);
  const res = makeRes();
  await handler({ method: 'GET', query: { assignment_name: 'Lab 2' } }, res, { getDb: () => db });
  assert.equal(res.body.data.length, 5, '5 with a real link across both courses; the empty placeholder is still dropped');
});

test('a course whose only resource doc has no link returns an empty list, not a broken entry', async () => {
  const db = makeDb([{ id: 'm1', assignment_name: 'Midterm 1', course_code: 'CS61A' }]); // no link field
  const res = makeRes();
  await handler({ method: 'GET', query: { assignment_name: 'Midterm 1', course_code: 'CS61A' } }, res, { getDb: () => db });
  assert.deepEqual(res.body.data, []);
});

test('missing assignment_name is rejected with 400', async () => {
  const res = makeRes();
  await handler({ method: 'GET', query: {} }, res, { getDb: () => makeDb([]) });
  assert.equal(res.statusCode, 400);
});
