import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

/** Pure w.r.t. its inputs, so it's testable without a real Firestore. */
export async function disconnectCanvas(db, email) {
  await db.collection('canvas_tokens').doc(email).delete();

  const deadlinesSnap = await db.collection('canvas_deadlines')
    .where('email', '==', email)
    .get();

  if (!deadlinesSnap.empty) {
    const batch = db.batch();
    let count = 0;
    for (const doc of deadlinesSnap.docs) {
      batch.delete(doc.ref);
      count++;
      // Firestore batch limit is 500
      if (count >= 500) {
        await batch.commit();
        count = 0;
      }
    }
    if (count > 0) {
      await batch.commit();
    }
  }

  await db.collection('students').doc(email).set(
    { canvas_connected: false, canvas_domain: null },
    { merge: true }
  );
}

// deps is overridable only for tests — production always uses the real
// verifyUserAuth/getDb via the defaults below.
export default async function handler(req, res, deps = {}) {
  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const dbFactory = deps.getDb || getDb;

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // The email comes from the verified token, never the request body, so a
  // request can only ever disconnect the account belonging to whoever is
  // actually logged in.
  const authResult = await verifyAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  try {
    await disconnectCanvas(dbFactory(), authResult.email);
    return res.status(200).json({ success: true });
  } catch (err) {
    console.error('Canvas disconnect error:', err);
    return res.status(500).json({ error: 'Internal server error', details: err.message });
  }
}
