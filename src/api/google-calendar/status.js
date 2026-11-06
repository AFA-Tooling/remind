import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

export default async function handler(req, res, deps = {}) {
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });
  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const authResult = await verifyAuth(req);
  if (!authResult.authorized) return res.status(401).json({ error: authResult.error });

  try {
    const db = (deps.getDb || getDb)();
    const token = await db.collection('google_calendar_tokens').doc(authResult.email).get();
    return res.status(200).json({ connected: token.exists });
  } catch (error) {
    console.error('Google Tasks status error:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
}
