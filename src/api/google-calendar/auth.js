import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { createAuthorizationUrl, createOAuthState, getOAuthStateId, isGoogleCalendarConfigured } from './googleClient.js';

const OAUTH_STATE_COOKIE = 'autore_google_oauth_state';
const OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60;

function isSecureRequest(req) {
  const forwardedProto = req.headers?.['x-forwarded-proto']?.split(',')[0].trim();
  return forwardedProto === 'https' ||
    !!req.socket?.encrypted ||
    process.env.GOOGLE_CALENDAR_REDIRECT_URI?.startsWith('https://');
}

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
    const cookieParts = [
      `${OAUTH_STATE_COOKIE}=${state}`,
      'Path=/api/google-calendar/callback',
      'HttpOnly',
      'SameSite=Lax',
      `Max-Age=${OAUTH_STATE_MAX_AGE_SECONDS}`,
    ];
    if (isSecureRequest(req)) cookieParts.push('Secure');
    res.setHeader('Set-Cookie', cookieParts.join('; '));
    return res.status(200).json({ authorization_url: createAuthorizationUrl(state) });
  } catch (error) {
    console.error('Google Tasks OAuth initiation error:', error.message);
    return res.status(500).json({ error: 'Could not start Google Tasks authorization' });
  }
}
