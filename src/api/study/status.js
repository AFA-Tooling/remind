// GET /api/study/status — returns the authenticated caller's study-gating status.
// The dashboard calls this on load to decide: render normally, show the lockout,
// or arm the waitlist popup.

import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { getStudyStatus } from './studyStatus.js';
import { LOCKOUT_MESSAGE, WAITLIST_MESSAGE } from './messages.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const authResult = await verifyUserAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  try {
    const status = await getStudyStatus(getDb(), authResult.email);
    const message =
      status.status === 'not_consented' ? LOCKOUT_MESSAGE :
      status.status === 'waitlisted' || status.status === 'pending' ? WAITLIST_MESSAGE :
      null;
    return res.status(200).json({ success: true, ...status, message });
  } catch (error) {
    console.error('Study status error:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
