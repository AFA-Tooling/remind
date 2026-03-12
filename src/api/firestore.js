// firestore.js - Shared Firebase Admin SDK initializer for API handlers
// Ensures Firebase is only initialized once across all server restarts.

import { initializeApp, getApps, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';

let db = null;

function getDb() {
    if (db) return db;

    if (!getApps().length) {
        const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT_JSON || '{}');
        initializeApp({
            credential: cert(serviceAccount),
            projectId: process.env.FIREBASE_PROJECT_ID,
        });
    }

    db = getFirestore();
    return db;
}

export { getDb };
