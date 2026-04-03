import { getDb } from '../firestore.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const email = (req.query.user_email || '').trim().toLowerCase();
  if (!email) {
    return res.status(400).json({ error: 'user_email query parameter is required' });
  }

  try {
    const db = getDb();
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

    return res.status(200).json({ success: true, data: deadlines });
  } catch (err) {
    console.error('Canvas deadlines error:', err);
    return res.status(500).json({ error: 'Internal server error', details: err.message });
  }
}
