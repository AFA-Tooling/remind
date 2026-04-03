import { getDb } from '../firestore.js';

export default async function handler(req, res) {
    if (req.method !== 'GET') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
        // Get user_email from query parameters
        const userEmail = req.query.user_email;

        if (!userEmail || typeof userEmail !== 'string') {
            return res.status(400).json({ error: 'user_email query parameter is required' });
        }

        const loginEmail = userEmail.trim().toLowerCase();

        const db = getDb();
        // Documents in 'students' collection are keyed by email
        const docSnap = await db.collection('students').doc(loginEmail).get();

        if (!docSnap.exists) {
            return res.status(404).json({ error: 'User not found' });
        }

        const data = docSnap.data();

        // Return user data
        return res.status(200).json({
            success: true,
            data: {
                preferred_first_name: data.preferred_first_name || null,
                phone_number: data.phone_number || null,
                discord_id: data.discord_id || null,
                days_before_deadline: data.days_before_deadline || 0,
                email_pref: data.email_pref || false,
                phone_pref: data.phone_pref || false,
                discord_pref: data.discord_pref || false,
                email: data.email,
                canvas_connected: data.canvas_connected || false,
                canvas_domain: data.canvas_domain || null
            }
        });

    } catch (error) {
        return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
}
