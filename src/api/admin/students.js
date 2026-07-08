// Admin endpoint: List all students
import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';
import { STUDY_PARTICIPANTS } from '../study/studyStatus.js';

const normEmail = email => (email || '').trim().toLowerCase();

// Classify a student against the study_participants map.
//   1 / 2      — assigned to that group
//   'unassigned' — has a participant doc but no group yet (registered, awaiting randomization)
//   'none'     — no participant doc (never registered for the study)
function classifyGroup(participants, email) {
  const key = normEmail(email);
  if (!participants.has(key)) return 'none';
  const group = participants.get(key);
  return group === 1 || group === 2 ? group : 'unassigned';
}

async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const db = getDb();
    const [snapshot, participantSnap] = await Promise.all([
      db.collection('students').get(),
      db.collection(STUDY_PARTICIPANTS).get(),
    ]);

    // email -> group (1 | 2 | null); presence in the map == registered for the study
    const participants = new Map(
      participantSnap.docs.map(doc => [normEmail(doc.id), doc.data().group ?? null])
    );

    const students = snapshot.docs.map(doc => ({
      id: doc.id,
      ...doc.data(),
      phone_number: doc.data().phone_number
        ? '***-***-' + doc.data().phone_number.slice(-4)
        : null,
      study_group: classifyGroup(participants, doc.data().email || doc.id),
    }));

    return res.status(200).json({ success: true, data: students, count: students.length });
  } catch (error) {
    console.error('Error fetching students:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}

export default requireAdmin(handler);
