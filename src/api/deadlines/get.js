import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

/**
 * Enrollment (and which course's deadlines to show) comes from the student's
 * own course_code — the same authoritative field every other route uses
 * (reminders/get.js, students/defaults.js). Previously this checked
 * assignment_submissions for /any/ row and then returned every deadline in
 * the whole collection with no course filter at all, so every student saw
 * every course's assignments mixed together.
 *
 * Takes `db` rather than calling getDb() itself so it's testable against a
 * fake Firestore without touching the real one.
 */
export async function getStudentDeadlines(db, userEmail) {
  const studentDoc = await db.collection('students').doc(userEmail).get();
  const courseCode = studentDoc.exists ? studentDoc.data()?.course_code : null;

  if (!courseCode) {
    return { enrolled: false, data: [] };
  }

  const snapshot = await db.collection('deadlines')
    .where('course_code', '==', courseCode)
    .get();
  const deadlines = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));

  deadlines.sort((a, b) => {
    const da = a.due ? new Date(a.due) : new Date(0);
    const db_ = b.due ? new Date(b.due) : new Date(0);
    return da - db_;
  });

  return { enrolled: true, data: deadlines };
}

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const authResult = await verifyUserAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  try {
    const result = await getStudentDeadlines(getDb(), authResult.email);
    return res.status(200).json({ success: true, ...result });
  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
