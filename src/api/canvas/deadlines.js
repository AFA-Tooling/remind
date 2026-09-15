import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

/** Pure w.r.t. its inputs, so it's testable without a real Firestore. */
export async function fetchCanvasDeadlines(db, email) {
  const snap = await db.collection('canvas_deadlines')
    .where('email', '==', email)
    .get();

  const deadlines = snap.docs.map(doc => {
    const data = doc.data();
    return {
      canvas_assignment_id: data.canvas_assignment_id,
      canvas_course_id: data.canvas_course_id,
      course_code: data.course_code,
      course_name: data.course_name,
      assignment_name: data.assignment_name,
      due: data.due,
      html_url: data.html_url,
      submission_state: data.submission_state,
      is_missing: data.is_missing,
      source: data.source,
    };
  });

  deadlines.sort((a, b) => {
    if (!a.due) return 1;
    if (!b.due) return -1;
    return new Date(a.due) - new Date(b.due);
  });

  return deadlines;
}

// deps is overridable only for tests — production always uses the real
// verifyUserAuth/getDb via the defaults below.
export default async function handler(req, res, deps = {}) {
  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const dbFactory = deps.getDb || getDb;

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // The email comes from the verified token, never the query string, so a
  // request can only ever read the Canvas deadlines belonging to whoever is
  // actually logged in.
  const authResult = await verifyAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  try {
    const deadlines = await fetchCanvasDeadlines(dbFactory(), authResult.email);
    return res.status(200).json({ success: true, data: deadlines });
  } catch (err) {
    console.error('Canvas deadlines error:', err);
    return res.status(500).json({ error: 'Internal server error', details: err.message });
  }
}
