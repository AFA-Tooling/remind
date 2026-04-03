// Admin authentication middleware
// Verifies Firebase ID tokens and checks against ADMIN_EMAILS allowlist

import { getAuth } from 'firebase-admin/auth';
import { getApps } from 'firebase-admin/app';
import { getDb } from '../firestore.js';

const ADMIN_EMAILS = (process.env.ADMIN_EMAILS || '').split(',').map(e => e.trim().toLowerCase()).filter(Boolean);

export async function verifyAdminAuth(req) {
  const authHeader = req.headers?.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;

  if (!token) {
    return { authorized: false, error: 'Missing authorization token' };
  }

  try {
    // Ensure Firebase is initialized
    if (!getApps().length) {
      getDb();
    }

    const decodedToken = await getAuth().verifyIdToken(token);
    const email = decodedToken.email?.toLowerCase();

    if (!email || !ADMIN_EMAILS.includes(email)) {
      return { authorized: false, error: 'Not an admin user' };
    }

    return { authorized: true, user: { email, uid: decodedToken.uid } };
  } catch (error) {
    console.error('Auth error:', error.message);
    return { authorized: false, error: 'Invalid token' };
  }
}

export function requireAdmin(handler) {
  return async (req, res) => {
    const auth = await verifyAdminAuth(req);
    if (!auth.authorized) {
      return res.status(403).json({ error: auth.error });
    }
    req.adminUser = auth.user;
    return handler(req, res);
  };
}
