import { CANVAS_CLIENT_ID, CANVAS_DEFAULT_DOMAIN, signState } from './canvasClient.js';

export default function handler(req, res) {
  const email = req.query.user_email;
  const domain = req.query.canvas_domain || CANVAS_DEFAULT_DOMAIN;

  if (!email) {
    return res.status(400).json({ error: 'user_email query parameter is required' });
  }

  if (!CANVAS_CLIENT_ID) {
    return res.status(500).json({ error: 'Canvas integration not configured' });
  }

  const redirectUri = process.env.CANVAS_REDIRECT_URI;
  const state = signState({ email: email.trim().toLowerCase(), domain, ts: Date.now() });

  const authUrl = new URL(`https://${domain}/login/oauth2/auth`);
  authUrl.searchParams.set('client_id', CANVAS_CLIENT_ID);
  authUrl.searchParams.set('response_type', 'code');
  authUrl.searchParams.set('redirect_uri', redirectUri);
  authUrl.searchParams.set('state', state);

  return res.redirect(302, authUrl.toString());
}
