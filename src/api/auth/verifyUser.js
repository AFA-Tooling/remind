import { getAuth } from 'firebase-admin/auth';
import { getApps } from 'firebase-admin/app';
import { getDb } from '../firestore.js';

export async function verifyUserAuth(req) {
  const authHeader = req.headers?.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : null;

  if (!token) {
    return { authorized: false, error: 'Missing authorization token' };
  }

  try {
    if (!getApps().length) {
      getDb();
    }
    const decoded = await getAuth().verifyIdToken(token);
    return { authorized: true, email: decoded.email?.toLowerCase(), uid: decoded.uid };
  } catch (error) {
    return { authorized: false, error: 'Invalid token' };
  }
}
