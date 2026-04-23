import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const authResult = await verifyUserAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  const userEmail = authResult.email;

  try {
    const db = getDb();

    // Check enrollment: student is in the course if their email appears
    // in assignment_submissions (mirrored from the GradeSync spreadsheet)
    const submissionSnap = await db.collection('assignment_submissions')
      .where('email', '==', userEmail)
      .limit(1)
      .get();

    if (submissionSnap.empty) {
      return res.status(200).json({ success: true, enrolled: false, data: [] });
    }

    const snapshot = await db.collection('deadlines').get();
    const deadlines = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));

    // Sort ascending by due date
    deadlines.sort((a, b) => {
      const da = a.due ? new Date(a.due) : new Date(0);
      const db_ = b.due ? new Date(b.due) : new Date(0);
      return da - db_;
    });

    return res.status(200).json({ success: true, enrolled: true, data: deadlines });
  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
