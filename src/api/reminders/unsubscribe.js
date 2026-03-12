import { getDb } from '../firestore.js';

export default async function handler(req, res) {
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
        let body = req.body;
        if (typeof body === 'string') {
            try {
                body = JSON.parse(body);
            } catch (e) {
                return res.status(400).json({ error: 'Invalid JSON body' });
            }
        }

        const { platforms = [], user_email, email } = body;
        // Prefer user_email, fallback to email
        const targetEmail = (user_email || email);

        if (!targetEmail || typeof targetEmail !== 'string') {
            return res.status(400).json({ error: 'Missing user email in request' });
        }

        const updates = {};
        const platformList = Array.isArray(platforms) ? platforms : [platforms];

        if (platformList.includes('all')) {
            updates.email_pref = false;
            updates.phone_pref = false;
            updates.discord_pref = false;
        } else {
            if (platformList.includes('email')) updates.email_pref = false;
            if (platformList.includes('sms')) updates.phone_pref = false;
            if (platformList.includes('discord')) updates.discord_pref = false;
        }

        if (Object.keys(updates).length === 0) {
            return res.status(400).json({ error: 'No valid platforms provided' });
        }

        const db = getDb();
        const docRef = db.collection('students').doc(targetEmail.trim().toLowerCase());
        await docRef.update(updates);
        const updated = (await docRef.get()).data();

        return res.status(200).json({ success: true, message: 'Unsubscribed successfully', data: updated });

    } catch (error) {
        console.error('Unsubscribe handler error:', error);
        return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
}
