import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { publicCourseConfig } from '../../shared/courses.js';
import { syncStudentCourseFromRoster } from '../students/syncCourse.js';

/**
 * POST /api/reminders/sync-course
 * Re-read class_roster and update the caller's students.course_code.
 */
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const authResult = await verifyUserAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  try {
    const db = getDb();
    const loginEmail = authResult.email;
    const studentSnap = await db.collection('students').doc(loginEmail).get();
    if (!studentSnap.exists) {
      return res.status(404).json({ error: 'User not found' });
    }

    const synced = await syncStudentCourseFromRoster(db, loginEmail, studentSnap.data());
    const courseCode = synced.courseCode || synced.data?.course_code || null;

    return res.status(200).json({
      success: true,
      patched: synced.patched,
      on_roster: synced.onRoster,
      course_code: courseCode,
      course: publicCourseConfig(courseCode),
      category_prefs: synced.data?.category_prefs || null,
    });
  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
