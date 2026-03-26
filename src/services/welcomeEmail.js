/**
 * Welcome Email Service
 *
 * Sends welcome emails to new AutoRemind users via Python subprocess.
 * Reuses the existing Gmail infrastructure (gmail_service.py).
 */

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Path to the Python script
const SCRIPT_PATH = path.join(__dirname, '..', '..', 'services', 'email-service', 'send_welcome_email.py');

/**
 * Send a welcome email to a new user.
 *
 * @param {Object} userData - User data for the welcome email
 * @param {string} userData.email - User's email address
 * @param {string} userData.preferred_name - User's preferred name
 * @param {Object} userData.channels - Channel preferences (email, sms, discord)
 * @param {number} userData.days_before - Days before deadline for reminders
 * @returns {Promise<{success: boolean, error?: string}>}
 */
async function sendWelcomeEmail(userData) {
  return new Promise((resolve) => {
    try {
      const jsonData = JSON.stringify(userData);

      const child = spawn('python3', [SCRIPT_PATH, jsonData], {
        cwd: path.dirname(SCRIPT_PATH),
        env: { ...process.env }
      });

      let stdout = '';
      let stderr = '';

      child.stdout.on('data', (data) => {
        stdout += data.toString();
      });

      child.stderr.on('data', (data) => {
        stderr += data.toString();
      });

      child.on('close', () => {
        if (stderr) {
          console.log('[WelcomeEmail] Python logs:', stderr);
        }

        // Try to parse stdout as JSON
        try {
          const result = JSON.parse(stdout.trim());
          resolve(result);
        } catch (parseError) {
          // If we can't parse JSON, return error
          console.error('[WelcomeEmail] Failed to parse response:', stdout);
          resolve({
            success: false,
            error: `Failed to parse response: ${stdout || 'No output'}`
          });
        }
      });

      child.on('error', (err) => {
        console.error('[WelcomeEmail] Process error:', err);
        resolve({
          success: false,
          error: `Process error: ${err.message}`
        });
      });

    } catch (error) {
      console.error('[WelcomeEmail] Error:', error);
      resolve({
        success: false,
        error: error.message
      });
    }
  });
}

export { sendWelcomeEmail };
