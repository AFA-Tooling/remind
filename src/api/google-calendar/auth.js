import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { createAuthorizationUrl, createOAuthState, getOAuthStateId, isGoogleCalendarConfigured } from './googleClient.js';

export default async function handler(req, res, deps = {}) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  if (!isGoogleCalendarConfigured()) {
    return res.status(503).json({ error: 'Google Tasks integration is not configured' });
  }
  const authResult = await (deps.verifyUserAuth || verifyUserAuth)(req);
  if (!authResult.authorized) return res.status(401).json({ error: authResult.error });
  if (!authResult.email) return res.status(401).json({ error: 'Authenticated account has no email address' });

  try {
    const state = createOAuthState();
    await (deps.getDb || getDb)().collection('google_calendar_oauth_states').doc(getOAuthStateId(state)).set({
      email: authResult.email,
      created_at: new Date().toISOString(),
    });
    return res.status(200).json({ authorization_url: createAuthorizationUrl(state) });
  } catch (error) {
    console.error('Google Tasks OAuth initiation error:', error.message);
    return res.status(500).json({ error: 'Could not start Google Tasks authorization' });
  }
}
