import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { getStudyStatus } from '../study/studyStatus.js';
import { LOCKOUT_MESSAGE } from '../study/messages.js';

// The daily pipeline routes each student to an assignment catalog by course_code.
// A student doc without it matches no catalog and silently receives nothing, so
// registration must always set one.
export const DEFAULT_COURSE_CODE = process.env.COURSE_CODE || 'CS61A';

// The class roster is authoritative; students who registered but are not on it
// (staff, late adds) still need a course to be reachable.
export function resolveCourseCode(rosterEntry) {
  return rosterEntry?.course_code || DEFAULT_COURSE_CODE;
}

export function buildNewStudent({ email, displayName, courseCode }) {
  const now = new Date().toISOString();
  return {
    email,
    preferred_first_name: displayName ? displayName.split(' ')[0] : null,
    course_code: courseCode,
    phone_number: null,
    discord_id: null,
    days_before_deadline: 1,
    release_reminder: true,
    email_pref: false,
    phone_pref: false,
    discord_pref: false,
    created_at: now,
    updated_at: now,
  };
}

// Creates a minimal student document on first login (idempotent — no-op if already exists).
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const authResult = await verifyUserAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  try {
    let body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
    const { display_name } = body || {};

    const loginEmail = authResult.email;
    if (!loginEmail) {
      return res.status(400).json({ error: 'user_email is required' });
    }

    const db = getDb();

    // Study-gating: don't create a student doc for non-consented users.
    const study = await getStudyStatus(db, loginEmail);
    if (study.status === 'not_consented') {
      return res.status(403).json({ error: 'Not consented', code: 'NOT_CONSENTED', message: LOCKOUT_MESSAGE });
    }

    const docRef = db.collection('students').doc(loginEmail);
    const existing = await docRef.get();

    if (existing.exists) {
      return res.status(200).json({ success: true, created: false, data: existing.data() });
    }

    const rosterSnap = await db.collection('class_roster').doc(loginEmail).get();
    const newStudent = buildNewStudent({
      email: loginEmail,
      displayName: display_name,
      courseCode: resolveCourseCode(rosterSnap.exists ? rosterSnap.data() : null),
    });

    await docRef.set(newStudent);
    return res.status(201).json({ success: true, created: true, data: newStudent });

  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
