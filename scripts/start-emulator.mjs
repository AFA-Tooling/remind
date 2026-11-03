// Start the local Firestore emulator (see docs/local-testing.md).
//
// Uses FIREBASE_PROJECT_ID from .env.local as the emulator's project, because the
// emulator keeps data separately per project ID and the Python scripts and web
// app both connect with that ID. Nothing here talks to the real project: the
// emulator is a local process, and Firestore traffic only reaches it when
// USE_FIRESTORE_EMULATOR=true (or FIRESTORE_EMULATOR_HOST) is set.

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
dotenv.config({ path: path.join(root, '.env.local') });

const projectId = (process.env.FIREBASE_PROJECT_ID || '').trim();
if (!projectId) {
  console.error('FIREBASE_PROJECT_ID is not set in .env.local; the emulator needs it to match the app.');
  process.exit(1);
}

const args = ['--yes', 'firebase-tools', 'emulators:start', '--only', 'firestore', '--project', projectId];
console.log(`Starting Firestore emulator for project "${projectId}" (UI: http://127.0.0.1:4000)`);

const child = spawn('npx', args, { cwd: root, stdio: 'inherit', shell: process.platform === 'win32' });
child.on('exit', (code) => process.exit(code ?? 0));
