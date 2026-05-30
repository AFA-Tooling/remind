// Admin endpoint: CRUD for deadlines + unmatched assignment discovery
import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';

function makeDocId(courseCode, assignmentName) {
  return `${courseCode}__${assignmentName}`.replace(/[/ ]/g, '_');
}

async function handler(req, res) {
  const db = getDb();

  try {
    if (req.method === 'GET') {
      // ?view=unmatched — assignments in submissions that have no deadline entry
      if (req.query?.view === 'unmatched') {
        const [submissionsSnap, deadlinesSnap] = await Promise.all([
          db.collection('assignment_submissions').select('assignment_name', 'category').get(),
          db.collection('deadlines').select('assignment_name').get(),
        ]);

        const deadlineNames = new Set(
          deadlinesSnap.docs
            .map(d => (d.data().assignment_name || '').toLowerCase().trim())
            .filter(Boolean)
        );

        const seen = new Map();
        for (const doc of submissionsSnap.docs) {
          const { assignment_name, category } = doc.data();
          const name = (assignment_name || '').trim();
          if (!name) continue;
          const key = name.toLowerCase();
          if (seen.has(key)) {
            seen.get(key).count++;
          } else {
            seen.set(key, { assignment_name: name, category: category || '', count: 1 });
          }
        }

        const unmatched = [...seen.values()]
          .filter(a => !deadlineNames.has(a.assignment_name.toLowerCase()))
          .sort((a, b) => a.assignment_name.localeCompare(b.assignment_name));

        return res.status(200).json({ success: true, data: unmatched });
      }

      // List all deadlines
      const snapshot = await db.collection('deadlines').get();
      const deadlines = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
      deadlines.sort((a, b) => {
        const da = a.due ? new Date(a.due) : new Date(0);
        const db_ = b.due ? new Date(b.due) : new Date(0);
        return da - db_;
      });
      return res.status(200).json({ success: true, data: deadlines, count: deadlines.length });
    }

    if (req.method === 'POST') {
      const { course_code = '', assignment_code, assignment_name, due } = req.body || {};
      if (!assignment_name || !due) {
        return res.status(400).json({ error: 'assignment_name and due are required' });
      }
      const docId = makeDocId(course_code, assignment_name);
      const record = {
        course_code,
        assignment_name,
        due,
        updated_at: new Date().toISOString(),
      };
      if (assignment_code) record.assignment_code = assignment_code;
      await db.collection('deadlines').doc(docId).set(record, { merge: true });
      return res.status(200).json({ success: true, id: docId });
    }

    if (req.method === 'PUT') {
      const { id, course_code = '', assignment_code, assignment_name, due } = req.body || {};
      if (!id || !assignment_name || !due) {
        return res.status(400).json({ error: 'id, assignment_name, and due are required' });
      }
      const record = {
        course_code,
        assignment_name,
        due,
        updated_at: new Date().toISOString(),
      };
      if (assignment_code !== undefined) record.assignment_code = assignment_code;
      await db.collection('deadlines').doc(id).set(record, { merge: true });
      return res.status(200).json({ success: true });
    }

    if (req.method === 'DELETE') {
      const { id } = req.body || {};
      if (!id) return res.status(400).json({ error: 'id is required' });
      await db.collection('deadlines').doc(id).delete();
      return res.status(200).json({ success: true });
    }

    return res.status(405).json({ error: 'Method not allowed' });
  } catch (error) {
    console.error('Admin deadlines error:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}

export default requireAdmin(handler);
