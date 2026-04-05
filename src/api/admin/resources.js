// Admin endpoint: CRUD for assignment resources
import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';

async function handler(req, res) {
  const db = getDb();
  const collection = db.collection('assignment_resources');

  // GET - List all resources
  if (req.method === 'GET') {
    try {
      const snapshot = await collection.get();
      const resources = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
      return res.status(200).json({ success: true, data: resources, count: resources.length });
    } catch (error) {
      return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
  }

  // POST - Create new resource
  if (req.method === 'POST') {
    try {
      const { assignment_name, assignment_code, course_code, resource_name, resource_type, link } = req.body;

      if (!assignment_name || !resource_name || !link) {
        return res.status(400).json({ error: 'Missing required fields: assignment_name, resource_name, link' });
      }

      const newResource = {
        assignment_name,
        assignment_code: assignment_code || assignment_name.split(':')[0].trim(),
        course_code: course_code || '',
        resource_name,
        resource_type: resource_type || 'Link',
        link,
        created_at: new Date().toISOString(),
        created_by: req.adminUser.email
      };

      const docRef = await collection.add(newResource);
      return res.status(201).json({ success: true, data: { id: docRef.id, ...newResource } });
    } catch (error) {
      return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
  }

  // PUT - Update existing resource
  if (req.method === 'PUT') {
    try {
      const { id, ...updates } = req.body;
      if (!id) return res.status(400).json({ error: 'Resource id is required' });

      const docRef = collection.doc(id);
      const doc = await docRef.get();
      if (!doc.exists) return res.status(404).json({ error: 'Resource not found' });

      const allowedFields = ['assignment_name', 'assignment_code', 'course_code', 'resource_name', 'resource_type', 'link'];
      const sanitizedUpdates = { updated_at: new Date().toISOString(), updated_by: req.adminUser.email };
      for (const field of allowedFields) {
        if (updates[field] !== undefined) sanitizedUpdates[field] = updates[field];
      }

      await docRef.update(sanitizedUpdates);
      const updated = await docRef.get();
      return res.status(200).json({ success: true, data: { id: doc.id, ...updated.data() } });
    } catch (error) {
      return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
  }

  // DELETE - Delete resource
  if (req.method === 'DELETE') {
    try {
      const { id } = req.body;
      if (!id) return res.status(400).json({ error: 'Resource id is required' });

      const docRef = collection.doc(id);
      const doc = await docRef.get();
      if (!doc.exists) return res.status(404).json({ error: 'Resource not found' });

      await docRef.delete();
      return res.status(200).json({ success: true, message: 'Resource deleted' });
    } catch (error) {
      return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
  }

  return res.status(405).json({ error: 'Method not allowed' });
}

export default requireAdmin(handler);
