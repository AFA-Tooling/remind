import test from 'node:test';
import assert from 'node:assert/strict';

import {
  assignmentKey,
  combineSourceAssignments,
  dueDay,
  mergeDuplicateReviewItems,
  outsideTermChecker,
  publishedNameReasons,
  termDateRange,
  websiteItemsCoveredByGradescope,
} from './combineSources.js';

const gs = (id, title, due) => ({ id, title, due, html_url: `https://www.gradescope.com/courses/1/assignments/${id}` });
const web = (id, title, due) => ({ id, title, due, html_url: 'https://cs.example.edu/', source: 'website', resources: [] });

test('assignments match on kind and number, keeping deadline-changing qualifiers', () => {
  assert.equal(assignmentKey('Coding HW3: IntLists'), 'homework 3');
  assert.equal(assignmentKey('Homework 3'), 'homework 3');
  assert.equal(assignmentKey('Project 4 in Rust'), 'project 4');
  assert.equal(assignmentKey('Proj 4'), 'project 4');
  assert.equal(assignmentKey('Project 1 Checkpoint 2'), 'project 1 checkpoint 2');
  assert.equal(assignmentKey('Homework 1 Part 2'), 'homework 1 part 2');
  assert.equal(assignmentKey('Midterm Part 1 Retake'), 'midterm part 1 retake');
  assert.equal(assignmentKey('Final Exam'), 'final exam');
  assert.equal(assignmentKey('Postterm 3: with Snap! - HOFs (MKH)'), 'postterm 3');
  assert.equal(assignmentKey('Post-term 3'), 'postterm 3');
  assert.equal(assignmentKey('Hog Strategy Contest'), null);
});

test('Gradescope due times are compared by Berkeley calendar day', () => {
  assert.equal(dueDay('2026-09-25'), '2026-09-25');
  assert.equal(dueDay('2026-09-26T06:59:00Z'), '2026-09-25'); // 11:59 PM Pacific
  assert.equal(dueDay('2026-09-25T23:59:00-07:00'), '2026-09-25');
  assert.equal(dueDay(null), null);
});

test('a website item and its Gradescope item become one item with Gradescope details', () => {
  const combined = combineSourceAssignments(
    [gs('101', 'HW3: Recursion', '2026-09-25T06:59:00Z')],
    [web('w1', 'Homework 3', '2026-09-24')],
  );
  assert.equal(combined.length, 1);
  assert.equal(combined[0].title, 'HW3: Recursion');
  assert.equal(combined[0].due, '2026-09-25T06:59:00Z');
  assert.equal(combined[0].source, 'gradescope');
  assert.deepEqual(combined[0].source_ids, ['101', 'w1']);
});

test('when Gradescope and the website disagree on the date, the instructor chooses', () => {
  const combined = combineSourceAssignments(
    [gs('101', 'Project 2', '2026-10-19T06:59:00Z')],
    [web('w1', 'Project 2', '2026-10-15')],
  );
  assert.equal(combined.length, 1);
  assert.equal(combined[0].title, 'Project 2');
  assert.equal(combined[0].due, null);
  assert.deepEqual(combined[0].review_reasons, ['Versions are due on different days. Use Edit to choose the due date.']);
  assert.deepEqual(
    combined[0].merged_versions.map(version => [version.assignment_name, version.due, version.source]),
    [['Project 2', '2026-10-19T06:59:00Z', 'gradescope'], ['Project 2', '2026-10-15', 'website']],
  );
  assert.deepEqual(combined[0].source_ids, ['101', 'w1']);
});

test('a website date matching Gradescope (or no website date) keeps Gradescope’s date', () => {
  const combined = combineSourceAssignments(
    [gs('101', 'Homework 5', '2026-10-20T06:59:00Z'), gs('102', 'Homework 6', '2026-10-27T06:59:00Z')],
    [web('w1', 'Homework 5', '2026-10-19'), web('w2', 'Homework 6', null)],
  );
  assert.deepEqual(combined.map(item => [item.title, item.due, item.review_reasons, item.merged_versions.length]), [
    ['Homework 5', '2026-10-20T06:59:00Z', undefined, 2],
    ['Homework 6', '2026-10-27T06:59:00Z', undefined, 2],
  ]);
});

test('a generic website deadline combines several Gradescope versions due the same day', () => {
  const combined = combineSourceAssignments(
    [
      gs('201', 'Project 4 in Rust', '2026-06-07'),
      gs('202', 'Project 4 in Python', '2026-06-07'),
      gs('203', 'Homework 1', '2026-06-01'),
    ],
    [web('w4', 'Project 4', '2026-06-07')],
  );
  assert.deepEqual(combined.map(item => item.title), ['Project 4', 'Homework 1']);
  const project = combined[0];
  assert.equal(project.due, '2026-06-07');
  assert.equal(project.source, 'gradescope');
  assert.deepEqual(project.combined_titles, ['Project 4 in Rust', 'Project 4 in Python']);
  // Every version stays visible so the instructor can pick any of them.
  assert.deepEqual(
    project.merged_versions.map(version => [version.assignment_name, version.source]),
    [['Project 4 in Rust', 'gradescope'], ['Project 4 in Python', 'gradescope'], ['Project 4', 'website']],
  );
  assert.deepEqual(project.source_ids, ['201', '202', 'w4']);
});

test('Gradescope versions with different dates are not merged into one', () => {
  const combined = combineSourceAssignments(
    [gs('201', 'Project 4 in Rust', '2026-06-07'), gs('202', 'Project 4 in Python', '2026-06-09')],
    [web('w4', 'Project 4', '2026-06-07')],
  );
  assert.deepEqual(
    combined.map(item => [item.title, item.source_ids]),
    [['Project 4 in Rust', ['201', 'w4']], ['Project 4 in Python', ['202']]],
  );
});

test('unmatched items from either source are all kept, including Gradescope discussions', () => {
  const combined = combineSourceAssignments(
    [gs('301', 'Discussion 3', '2026-09-18'), gs('302', 'Homework 2', '2026-09-11')],
    [web('w1', 'Lab 2', null), web('w2', 'Lab 2', '2026-09-09'), web('w3', 'Midterm', '2026-10-20')],
  );
  assert.deepEqual(
    combined.map(item => item.title),
    ['Discussion 3', 'Homework 2', 'Lab 2', 'Lab 2', 'Midterm'],
  );
});

test('website items already covered by the course’s Gradescope items are recognized', () => {
  const existing = [
    { assignment_id: '201', assignment_name: 'Project 4 in Rust', due: '2026-06-07', source: 'gradescope' },
    { assignment_id: '202', assignment_name: 'Project 4 in Python', due: '2026-06-07', source: 'gradescope' },
    { assignment_id: 'w9', assignment_name: 'Lab 9', due: null, source: 'website' },
  ];
  const covered = websiteItemsCoveredByGradescope(existing, [
    web('w4', 'Project 4', '2026-06-07'),
    web('w5', 'Homework 5', '2026-06-01'),
  ]);
  assert.deepEqual([...covered], [['w4', ['201', '202']]]);
});

test('a later website date that disagrees with Gradescope is not treated as covered', () => {
  const existing = [
    { assignment_id: '102', assignment_name: 'Project 2: Spelling Bee', due: '2026-10-03T06:59:00Z', source: 'gradescope' },
    { assignment_id: '103', assignment_name: 'Project 3: 2048', due: '2026-10-20T06:59:00Z', source: 'gradescope' },
  ];
  const covered = websiteItemsCoveredByGradescope(existing, [
    web('w2', 'Project 2', '2026-10-01'),
    web('w3', 'Project 3', '2026-10-19'),
  ]);
  assert.deepEqual([...covered], [['w3', ['103']]]);
});

const staged = (id, assignment_name, due, source = 'gradescope') => ({
  assignment_id: id, assignment_name, due, source, html_url: '', resources: [], review_reasons: [],
});

test('versions of one deadline merge into one item with the most likely due date', () => {
  const { items, removedIds } = mergeDuplicateReviewItems([
    staged('1', 'Lab 2: Build Your Own Blocks (Code)', '2026-09-10'),
    staged('2', 'Lab 2: Build Your Own Blocks (Conceptual)', '2026-09-10'),
    staged('3', 'Optional Lab 2: Object-Oriented Programming (Code)', '2026-09-12'),
    staged('4', 'Homework 1', '2026-09-05'),
  ]);
  assert.deepEqual(removedIds, ['2', '3']);
  assert.deepEqual(items.map(item => [item.assignment_id, item.assignment_name, item.due]), [
    ['1', 'Lab 2', null],
    ['4', 'Homework 1', '2026-09-05'],
  ]);
  assert.deepEqual(items[0].source_ids, ['1', '2', '3']);
  assert.deepEqual(items[0].merged_versions.map(version => version.assignment_name), [
    'Lab 2: Build Your Own Blocks (Code)',
    'Lab 2: Build Your Own Blocks (Conceptual)',
    'Optional Lab 2: Object-Oriented Programming (Code)',
  ]);
  // The versions disagree on the day, so the instructor chooses the date.
  assert.deepEqual(items[0].review_reasons, [
    'Versions are due on different days. Use Edit to choose the due date.',
  ]);
});

test('versions that agree on the day merge with nothing to check', () => {
  const { items } = mergeDuplicateReviewItems([
    staged('w', 'Project 5', null, 'website'),
    staged('g', 'Project 5 RESUBMISSION: Final Project Submission', '2026-12-10T07:59:00Z'),
  ]);
  assert.deepEqual(items.map(item => [item.assignment_id, item.assignment_name, item.due, item.review_reasons]), [
    ['g', 'Project 5', '2026-12-10T07:59:00Z', []],
  ]);
});

test('a version without a date takes the date of the others', () => {
  const { items } = mergeDuplicateReviewItems([
    staged('w', 'Homework 4', null, 'website'),
    staged('g', 'HW4: Trees', '2026-10-02T06:59:00Z'),
    staged('x', 'Homework 4', '2026-10-01', 'website'),
  ]);
  // Gradescope's due time is used for the shared day.
  assert.deepEqual(items.map(item => [item.assignment_name, item.due, item.review_reasons]), [
    ['Homework 4', '2026-10-02T06:59:00Z', []],
  ]);
});

test('an already merged item absorbs later versions', () => {
  const first = mergeDuplicateReviewItems([
    staged('1', 'Lab 2 (Code)', '2026-09-10'),
    staged('2', 'Lab 2 (Conceptual)', '2026-09-10'),
  ]).items;
  const { items } = mergeDuplicateReviewItems([...first, staged('5', 'Lab 2 (Extra)', '2026-09-10')]);
  assert.equal(items.length, 1);
  assert.equal(items[0].merged_versions.length, 3);
  assert.deepEqual(items[0].source_ids, ['1', '2', '5']);
});

test('versions with conflicting dates all outside the term merge with no due date', () => {
  const { items } = mergeDuplicateReviewItems([
    staged('a', 'Postterm 3: with Snap! - COMBINE (C)', '2050-11-05'),
    staged('b', 'Postterm 3: with Snap! - HOFs (MKH)', '2050-11-05'),
    staged('c', 'Postterm 3: with Snap! - Recursion (R)', '2050-11-05'),
    staged('d', 'Postterm 3: With Snap! (HOFs)', '2052-06-14'),
    staged('e', 'Postterm 3: With Snap! (Recursion)', '2052-06-14'),
  ], outsideTermChecker('Fall 2026'));
  assert.equal(items.length, 1);
  assert.equal(items[0].assignment_name, 'Postterm 3');
  assert.equal(items[0].due, null);
  assert.equal(items[0].merged_versions.length, 5);
  assert.deepEqual(items[0].review_reasons, [
    'Versions are due on different days. Use Edit to choose the due date.',
  ]);
});

test('versions agreeing on one day keep it, even outside the term', () => {
  const { items } = mergeDuplicateReviewItems([
    staged('a', 'Lab 5: Lists + HOFs (Conceptual)', '2050-08-15'),
    staged('b', 'Lab 5: Lists + HOFs (Code)', '2050-08-15'),
  ], outsideTermChecker('Fall 2026'));
  assert.deepEqual(items.map(item => [item.assignment_name, item.due, item.review_reasons]), [
    ['Lab 5', '2050-08-15', []],
  ]);
});

test('items named like a published assignment are noted', () => {
  const reasons = publishedNameReasons(
    [staged('n', 'Project 3', '2026-10-23'), staged('m', 'Lab 4', '2026-10-01')],
    [{ assignment_id: 'old', assignment_name: 'Project 3' }],
  );
  assert.deepEqual(Object.fromEntries(reasons), { n: ['Same name as “Project 3”, already in this course'] });
});

test('each term has a date range, from the term or the course website address', () => {
  assert.deepEqual(termDateRange('Fall 2026'), ['2026-07-15', '2027-01-31']);
  assert.deepEqual(termDateRange('Spring 2027'), ['2026-12-15', '2027-06-15']);
  assert.deepEqual(termDateRange('', 'https://cs61a.org/fa26/'), ['2026-07-15', '2027-01-31']);
  assert.equal(termDateRange('', 'https://www.eecs70.org/'), null);
});

test('Gradescope topic names combine with the website item whose page is that topic', () => {
  const gradescope = [
    { id: 'g1', title: 'Hog', due: '2026-09-17T23:59' },
    { id: 'g2', title: 'Hog Checkpoint', due: '2026-09-10T23:59' },
    { id: 'g3', title: 'Ants Checkpoint 2', due: '2026-10-21T23:59' },
    { id: 'g4', title: 'Scheme', due: '2026-08-24T23:59' },
  ];
  const website = [
    { id: 'w1', title: 'Project 1', due: '2026-09-17', html_url: 'https://cs61a.org/fa26/projects/hog/', source: 'website' },
    { id: 'w2', title: 'Project 1 Checkpoint 1', due: '2026-09-10', html_url: 'https://cs61a.org/fa26/projects/hog/', source: 'website' },
    { id: 'w3', title: 'Project 3 Checkpoint 2', due: '2026-10-21', html_url: 'https://cs61a.org/fa26/projects/ants/', source: 'website' },
    // Same topic but a different day, or no page of its own: not combined.
    { id: 'w4', title: 'Project 3 Checkpoint 1', due: '2026-10-16', html_url: 'https://cs61a.org/fa26/projects/ants/', source: 'website' },
    { id: 'w5', title: 'Quiz 1', due: null, html_url: 'https://cs61a.org/fa26/', source: 'website' },
  ];
  const combined = combineSourceAssignments(gradescope, website);
  assert.deepEqual(
    combined.map(item => [item.title, item.source, [...(item.source_ids || [item.id])].sort().join(',')]),
    [
      ['Hog', 'gradescope', 'g1,w1'],
      ['Hog Checkpoint', 'gradescope', 'g2,w2'],
      ['Ants Checkpoint 2', 'gradescope', 'g3,w3'],
      ['Scheme', 'gradescope', 'g4'],
      ['Project 3 Checkpoint 1', 'website', 'w4'],
      ['Quiz 1', 'website', 'w5'],
    ],
  );
});

test('different website deliverables of one project are not merged into one item', () => {
  const site = (id, name, due) => ({ assignment_id: id, assignment_name: name, due, source: 'website', resources: [] });
  const { items, removedIds } = mergeDuplicateReviewItems([
    site('a', 'Project 4 Research Document', '2026-10-28'),
    site('b', 'Project 4 Artifact', '2026-11-13'),
    site('c', 'Project 4 Peer Comments', '2026-11-20'),
    // Two versions of one deadline (same day) still merge.
    site('d', 'Project 5', '2026-12-02'),
    site('e', 'Project 5 TypeScript', '2026-12-02'),
  ]);
  assert.deepEqual(items.map(item => [item.assignment_name, item.due]), [
    ['Project 4 Research Document', '2026-10-28'],
    ['Project 4 Artifact', '2026-11-13'],
    ['Project 4 Peer Comments', '2026-11-20'],
    ['Project 5', '2026-12-02'],
  ]);
  assert.deepEqual(removedIds, ['e']);
});
