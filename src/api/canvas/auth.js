import { getAuth } from 'firebase-admin/auth';
import { getApps } from 'firebase-admin/app';
import { getDb } from '../firestore.js';
import { CANVAS_CLIENT_ID, CANVAS_DEFAULT_DOMAIN, signState } from './canvasClient.js';

export default async function handler(req, res) {
  const domain = req.query.canvas_domain || CANVAS_DEFAULT_DOMAIN;

  // This route is reached by a full top-level navigation (the browser is
  // redirected here, then on to Canvas), so it can't carry an Authorization
  // header the way a fetch() call can. A verified Firebase ID token passed as a query
  // param is the standard way to authenticate this specific kind of
  // redirect-only entry point; it's short-lived (~1hr) and still verified
  // server-side via the Admin SDK, same as every other route's Bearer token.
  const idToken = req.query.id_token;
  if (!idToken) {
    return res.status(400).json({ error: 'id_token query parameter is required' });
  }

  let email;
  try {
    if (!getApps().length) getDb();
    const decoded = await getAuth().verifyIdToken(idToken);
    email = decoded.email?.toLowerCase();
    if (!email) throw new Error('token has no email');
  } catch {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }

  if (!CANVAS_CLIENT_ID) {
    return res.status(500).json({ error: 'Canvas integration not configured' });
  }

  const redirectUri = process.env.CANVAS_REDIRECT_URI;
  const state = signState({ email, domain, ts: Date.now() });

  const authUrl = new URL(`https://${domain}/login/oauth2/auth`);
  authUrl.searchParams.set('client_id', CANVAS_CLIENT_ID);
  authUrl.searchParams.set('response_type', 'code');
  authUrl.searchParams.set('redirect_uri', redirectUri);
  authUrl.searchParams.set('state', state);

  return res.redirect(302, authUrl.toString());
}
