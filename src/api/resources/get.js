import { getDb } from '../firestore.js';

// deps is overridable only for tests — production always uses the real
// getDb via the default below.
export default async function handler(req, res, deps = {}) {
  const dbFactory = deps.getDb || getDb;

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const assignmentName = (req.query?.assignment_name || '').trim();
  const courseCode = (req.query?.course_code || '').trim();
  if (!assignmentName) {
    return res.status(400).json({ error: 'assignment_name is required' });
  }

  try {
    const db = dbFactory();
    // assignment_name alone isn't unique across courses — "Lab 2", "Midterm 1",
    // etc. exist in multiple courses with completely different (and wrong-for-
    // this-student) resource links, so without course_code every course's
    // same-named assignment gets mixed into one list.
    let query = db.collection('assignment_resources').where('assignment_name', '==', assignmentName);
    if (courseCode) {
      query = query.where('course_code', '==', courseCode);
    }
    const snapshot = await query.get();

    // Some assignment_resources docs are placeholder shells with no actual
    // link (e.g. exams that were never given a curated resource) — drop
    // those rather than rendering a broken "Resource: Link" pointing nowhere.
    const resources = snapshot.docs
      .map(doc => ({ id: doc.id, ...doc.data() }))
      .filter(r => r.link);

    return res.status(200).json({ success: true, data: resources });
  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
