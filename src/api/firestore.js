// firestore.js - Shared Firebase Admin SDK initializer for API handlers
// Ensures Firebase is only initialized once across all server restarts.

import { initializeApp, getApps, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';

let db = null;

// Local Firestore emulator (see docs/local-testing.md). Mirrors
// services/shared/settings.py: USE_FIRESTORE_EMULATOR=true in .env.local points
// every Firestore read/write at the emulator. Checked inside getDb() rather than
// at module load because server.js loads .env.local after its imports run.
// Firebase Auth is not redirected, so real sign-in still works locally.
const DEFAULT_FIRESTORE_EMULATOR_HOST = '127.0.0.1:8080';

// Returns true when Firestore traffic goes to the emulator.
function applyEmulatorSetting() {
    const flag = (process.env.USE_FIRESTORE_EMULATOR || '').trim().toLowerCase();
    if (['1', 'true', 'yes'].includes(flag) && !process.env.FIRESTORE_EMULATOR_HOST) {
        process.env.FIRESTORE_EMULATOR_HOST = DEFAULT_FIRESTORE_EMULATOR_HOST;
    }
    if (process.env.FIRESTORE_EMULATOR_HOST) {
        console.log(`[firestore] Using Firestore emulator at ${process.env.FIRESTORE_EMULATOR_HOST}`);
        return true;
    }
    return false;
}

function getDb() {
    if (db) return db;

    const usingEmulator = applyEmulatorSetting();

    if (!getApps().length) {
        if (usingEmulator) {
            // No service account in emulator mode: the emulator needs none, and the
            // only Auth call the app makes (verifyIdToken) needs just the project ID.
            // This also guarantees a local run holds no production write credential.
            initializeApp({ projectId: process.env.FIREBASE_PROJECT_ID });
        } else {
            const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT_JSON || '{}');
            initializeApp({
                credential: cert(serviceAccount),
                projectId: process.env.FIREBASE_PROJECT_ID,
            });
        }
    }

    db = getFirestore();
    return db;
}

export { getDb };
