import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { revokeToken } from './googleClient.js';

export default async function handler(req, res, deps = {}) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const authResult = await verifyAuth(req);
  if (!authResult.authorized) return res.status(401).json({ error: authResult.error });

  try {
    const db = (deps.getDb || getDb)();
    const tokenRef = db.collection('google_calendar_tokens').doc(authResult.email);
    const tokenSnapshot = await tokenRef.get();
    let revocationWarning = null;
    if (tokenSnapshot.exists) {
      try {
        await (deps.revokeToken || revokeToken)(tokenSnapshot.data().access_token);
      } catch (error) {
        revocationWarning = error.message;
      }
    }
    await tokenRef.delete();
    // Keep task links so reconnecting updates existing tasks instead of duplicating them.
    return res.status(200).json({ success: true, revocationWarning });
  } catch (error) {
    console.error('Google Tasks disconnect error:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
}
