import crypto from 'crypto';
import { getDb } from '../firestore.js';

const CANVAS_CLIENT_ID = process.env.CANVAS_CLIENT_ID;
const CANVAS_CLIENT_SECRET = process.env.CANVAS_CLIENT_SECRET;
const CANVAS_DEFAULT_DOMAIN = process.env.CANVAS_DEFAULT_DOMAIN || 'canvas.instructure.com';

// Token refresh buffer: refresh 5 minutes before expiry
const REFRESH_BUFFER_MS = 5 * 60 * 1000;

/**
 * Sign a state payload with HMAC-SHA256.
 */
export function signState(payload) {
  const data = JSON.stringify(payload);
  const hmac = crypto.createHmac('sha256', CANVAS_CLIENT_SECRET).update(data).digest('hex');
  const encoded = Buffer.from(data).toString('base64url');
  return `${encoded}.${hmac}`;
}

/**
 * Verify and decode a signed state parameter.
 * Returns the decoded payload or null if invalid.
 */
export function verifyState(state) {
  const dotIndex = state.lastIndexOf('.');
  if (dotIndex === -1) return null;

  const encoded = state.slice(0, dotIndex);
  const signature = state.slice(dotIndex + 1);

  let data;
  try {
    data = Buffer.from(encoded, 'base64url').toString('utf-8');
  } catch {
    return null;
  }

  const expected = crypto.createHmac('sha256', CANVAS_CLIENT_SECRET).update(data).digest('hex');
  if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) {
    return null;
  }

  try {
    const payload = JSON.parse(data);
    // Reject states older than 10 minutes
    if (Date.now() - payload.ts > 10 * 60 * 1000) return null;
    return payload;
  } catch {
    return null;
  }
}

/**
 * Exchange an authorization code for tokens.
 */
export async function exchangeCodeForTokens(domain, code, redirectUri) {
  const res = await fetch(`https://${domain}/login/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CANVAS_CLIENT_ID,
      client_secret: CANVAS_CLIENT_SECRET,
      redirect_uri: redirectUri,
      code,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Canvas token exchange failed (${res.status}): ${text}`);
  }

  return res.json();
}

/**
 * Refresh an access token using a refresh token.
 */
async function refreshAccessToken(domain, refreshToken) {
  const res = await fetch(`https://${domain}/login/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: CANVAS_CLIENT_ID,
      client_secret: CANVAS_CLIENT_SECRET,
      refresh_token: refreshToken,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Canvas token refresh failed (${res.status}): ${text}`);
  }

  return res.json();
}

/**
 * Get a valid access token for a user, refreshing if needed.
 * Updates Firestore with new token if refreshed.
 */
export async function getValidToken(db, email) {
  const docRef = db.collection('canvas_tokens').doc(email);
  const doc = await docRef.get();

  if (!doc.exists) {
    throw new Error('Canvas not connected for this user');
  }

  const data = doc.data();
  const expiresAt = new Date(data.token_expires_at).getTime();
  const now = Date.now();

  // Token still valid
  if (now < expiresAt - REFRESH_BUFFER_MS) {
    return { accessToken: data.access_token, domain: data.canvas_domain };
  }

  // Need to refresh
  const tokenData = await refreshAccessToken(data.canvas_domain, data.refresh_token);
  const newExpiresAt = new Date(now + (tokenData.expires_in || 3600) * 1000).toISOString();

  await docRef.update({
    access_token: tokenData.access_token,
    token_expires_at: newExpiresAt,
    ...(tokenData.refresh_token ? { refresh_token: tokenData.refresh_token } : {}),
  });

  return { accessToken: tokenData.access_token, domain: data.canvas_domain };
}

/**
 * Parse Link header for pagination.
 * Returns the URL for rel="next" or null.
 */
function parseNextLink(linkHeader) {
  if (!linkHeader) return null;
  const parts = linkHeader.split(',');
  for (const part of parts) {
    const match = part.match(/<([^>]+)>;\s*rel="next"/);
    if (match) return match[1];
  }
  return null;
}

/**
 * Fetch a Canvas API endpoint with pagination and rate limit handling.
 * Returns all results across all pages.
 */
export async function canvasFetch(domain, accessToken, path) {
  const results = [];
  let url = path.startsWith('http') ? path : `https://${domain}/api/v1${path}`;

  while (url) {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Canvas API error (${res.status}): ${text}`);
    }

    // Check rate limit
    const remaining = parseFloat(res.headers.get('x-rate-limit-remaining') || '100');
    if (remaining < 20) {
      // Back off for 1 second if getting close to the limit
      await new Promise(resolve => setTimeout(resolve, 1000));
    }

    const data = await res.json();
    if (Array.isArray(data)) {
      results.push(...data);
    } else {
      return data; // Single object response
    }

    url = parseNextLink(res.headers.get('link'));
  }

  return results;
}

export { CANVAS_CLIENT_ID, CANVAS_CLIENT_SECRET, CANVAS_DEFAULT_DOMAIN };
