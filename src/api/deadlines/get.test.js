import test from 'node:test';
import assert from 'node:assert/strict';

import { getStudentDeadlines } from './get.js';

// Regression coverage for the 2026-09-15 bug: every student saw every
// course's assignments mixed together, because this route fetched the
// entire `deadlines` collection with no course filter at all.

/** Minimal in-memory Firestore covering just what getStudentDeadlines touches. */
function makeDb(seed = {}) {
  const data = new Map();
  for (const [collection, docs] of Object.entries(seed)) {
    for (const [id, value] of Object.entries(docs)) data.set(`${collection}/${id}`, value);
  }

  return {
    collection(collection) {
      return {
        doc(id) {
          const key = `${collection}/${id}`;
          return {
            async get() {
              return { exists: data.has(key), data: () => data.get(key) };
            },
          };
        },
        where(field, op, value) {
          if (op !== '==') throw new Error(`fake only supports '==', got ${op}`);
          const docs = [...data.entries()]
            .filter(([k]) => k.startsWith(`${collection}/`))
            .filter(([, v]) => v[field] === value)
            .map(([k, v]) => ({ id: k.slice(k.indexOf('/') + 1), data: () => v }));
          return { async get() { return { docs }; } };
        },
      };
    },
  };
}

test('a student with no course_code is not enrolled and sees nothing', async () => {
  const db = makeDb({ students: { 'nobody@berkeley.edu': {} } });
  const result = await getStudentDeadlines(db, 'nobody@berkeley.edu');
  assert.deepEqual(result, { enrolled: false, data: [] });
});

test('a student with no students doc at all is not enrolled', async () => {
  const db = makeDb({});
  const result = await getStudentDeadlines(db, 'ghost@berkeley.edu');
  assert.deepEqual(result, { enrolled: false, data: [] });
});

test('only sees deadlines for their own course, not other courses mixed in', async () => {
  const db = makeDb({
    students: { 'jshaul@berkeley.edu': { course_code: 'CS61A' } },
    deadlines: {
      hog: { course_code: 'CS61A', assignment_name: 'Hog', due: '2026-09-17T23:59:59' },
      lab2_c: { course_code: 'CS61C', assignment_name: 'Lab 2', due: '2026-09-15T23:59:59' },
      wordle: { course_code: 'CS10', assignment_name: 'Project 1: Wordle-lite', due: '2026-09-16T23:59:59' },
    },
  });
  const result = await getStudentDeadlines(db, 'jshaul@berkeley.edu');
  assert.equal(result.enrolled, true);
  assert.equal(result.data.length, 1);
  assert.equal(result.data[0].assignment_name, 'Hog');
});

test('sorts the student\'s own deadlines ascending by due date', async () => {
  const db = makeDb({
    students: { 's@berkeley.edu': { course_code: 'CS61A' } },
    deadlines: {
      later: { course_code: 'CS61A', assignment_name: 'Later', due: '2026-09-20T23:59:59' },
      earlier: { course_code: 'CS61A', assignment_name: 'Earlier', due: '2026-09-05T23:59:59' },
    },
  });
  const result = await getStudentDeadlines(db, 's@berkeley.edu');
  assert.deepEqual(result.data.map(d => d.assignment_name), ['Earlier', 'Later']);
});

test('a deadline missing a due date sorts first rather than crashing', async () => {
  const db = makeDb({
    students: { 's@berkeley.edu': { course_code: 'CS61A' } },
    deadlines: {
      dated: { course_code: 'CS61A', assignment_name: 'Dated', due: '2026-09-05T23:59:59' },
      undated: { course_code: 'CS61A', assignment_name: 'Undated', due: null },
    },
  });
  const result = await getStudentDeadlines(db, 's@berkeley.edu');
  assert.deepEqual(result.data.map(d => d.assignment_name), ['Undated', 'Dated']);
});
