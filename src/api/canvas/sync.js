import { getDb } from '../firestore.js';
import { getValidToken, canvasFetch } from './canvasClient.js';

/**
 * Sync Canvas assignments for a single user into Firestore.
 * Used by both the callback (initial sync) and the POST endpoint (on-demand).
 */
export async function syncCanvasAssignments(db, email) {
  const { accessToken, domain } = await getValidToken(db, email);

  // Fetch active courses where user is a student
  const courses = await canvasFetch(domain, accessToken,
    '/courses?enrollment_state=active&enrollment_type=student&per_page=50'
  );

  const deadlineDocs = [];

  for (const course of courses) {
    // Fetch assignments with submission data
    let assignments;
    try {
      assignments = await canvasFetch(domain, accessToken,
        `/courses/${course.id}/assignments?include[]=submission&order_by=due_at&per_page=50`
      );
    } catch (err) {
      console.error(`Failed to fetch assignments for course ${course.id}:`, err.message);
      continue;
    }

    for (const assignment of assignments) {
      // Skip assignments without a due date
      if (!assignment.due_at) continue;

      const submission = assignment.submission || {};
      const docId = `${email}__${assignment.id}`;

      deadlineDocs.push({
        docId,
        data: {
          email,
          canvas_assignment_id: assignment.id,
          canvas_course_id: course.id,
          course_code: course.course_code || course.name || `Course ${course.id}`,
          course_name: course.name || '',
          assignment_name: assignment.name,
          due: assignment.due_at,
          html_url: assignment.html_url || '',
          submission_state: submission.workflow_state || 'unsubmitted',
          is_missing: submission.missing || false,
          source: 'canvas',
          synced_at: new Date().toISOString(),
        },
      });
    }
  }

  // Batch write all deadlines
  const collection = db.collection('canvas_deadlines');

  // Write new/updated docs
  for (let i = 0; i < deadlineDocs.length; i += 500) {
    const batch = db.batch();
    const chunk = deadlineDocs.slice(i, i + 500);
    for (const { docId, data } of chunk) {
      batch.set(collection.doc(docId), data);
    }
    await batch.commit();
  }

  // Remove stale deadlines (no longer on Canvas)
  const currentIds = new Set(deadlineDocs.map(d => d.docId));
  const existingSnap = await collection.where('email', '==', email).get();

  const staleDocs = existingSnap.docs.filter(doc => !currentIds.has(doc.id));
  if (staleDocs.length > 0) {
    for (let i = 0; i < staleDocs.length; i += 500) {
      const batch = db.batch();
      const chunk = staleDocs.slice(i, i + 500);
      for (const doc of chunk) {
        batch.delete(doc.ref);
      }
      await batch.commit();
    }
  }

  // Update last_sync_at
  await db.collection('canvas_tokens').doc(email).update({
    last_sync_at: new Date().toISOString(),
    sync_error: null,
  });

  return { synced: deadlineDocs.length, removed: staleDocs.length };
}

/**
 * POST /api/canvas/sync handler - on-demand sync from frontend.
 */
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const email = (req.body.user_email || '').trim().toLowerCase();
  if (!email) {
    return res.status(400).json({ error: 'user_email is required' });
  }

  try {
    const db = getDb();
    const result = await syncCanvasAssignments(db, email);
    return res.status(200).json({ success: true, ...result });
  } catch (err) {
    console.error('Canvas sync error:', err);

    // Update sync_error in Firestore
    try {
      const db = getDb();
      await db.collection('canvas_tokens').doc(email).update({
        sync_error: err.message,
      });
    } catch { /* ignore */ }

    return res.status(500).json({ error: 'Sync failed', details: err.message });
  }
}
