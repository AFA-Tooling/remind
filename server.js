import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import dotenv from 'dotenv';
import crypto from 'crypto';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load environment variables - use absolute path
const envPath = path.join(__dirname, '.env.local');
dotenv.config({ path: envPath });

// Import the serverless function logic
import settingsHandler from './api/reminders/settings.js';

// Use PORT from environment variable (GCP Cloud Run sets this) or default to 3000 for local dev
const PORT = process.env.PORT || 3000;

// // Password protection
// const CORRECT_PASSWORD = 'autoremind123@';
// const SESSION_COOKIE_NAME = 'autoremind_session';
// const SESSION_SECRET = process.env.SESSION_SECRET || 'autoremind-secret-key-change-in-production';

// // In-memory session store (in production, consider using Redis or database)
// const activeSessions = new Set();

// // Helper function to generate session token
// function generateSessionToken() {
//   return crypto.randomBytes(32).toString('hex');
// }

// // Helper function to verify session from cookie
// function getSessionFromCookie(cookieHeader) {
//   if (!cookieHeader) return null;
  
//   const cookies = cookieHeader.split(';').map(c => c.trim());
//   const sessionCookie = cookies.find(c => c.startsWith(`${SESSION_COOKIE_NAME}=`));
  
//   if (!sessionCookie) return null;
  
//   const token = sessionCookie.split('=')[1];
//   return activeSessions.has(token) ? token : null;
// }

// // Helper function to parse cookies
// function parseCookies(cookieHeader) {
//   const cookies = {};
//   if (!cookieHeader) return cookies;
  
//   cookieHeader.split(';').forEach(cookie => {
//     const parts = cookie.trim().split('=');
//     if (parts.length === 2) {
//       cookies[parts[0].trim()] = parts[1].trim();
//     }
//   });
//   return cookies;
// }

const server = http.createServer(async (req, res) => {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  // const cookieHeader = req.headers.cookie;
  // const isAuthenticated = getSessionFromCookie(cookieHeader) !== null;

  // Parse URL to get pathname (without query string)
  let urlPath = req.url || '/';
  let queryString = '';
  if (urlPath.includes('?')) {
    const parts = urlPath.split('?');
    urlPath = parts[0];
    queryString = parts[1];
  }
  
  // Ensure urlPath starts with /
  if (!urlPath.startsWith('/')) {
    urlPath = '/' + urlPath;
  }

  // // Handle password authentication endpoint
  // if (req.url === '/api/auth/password' || urlPath === '/api/auth/password') {
  //   let body = '';
  //   req.on('data', chunk => {
  //     body += chunk.toString();
  //   });

  //   req.on('end', () => {
  //     try {
  //       const data = JSON.parse(body);
        
  //       if (data.password === CORRECT_PASSWORD) {
  //         // Generate session token
  //         const sessionToken = generateSessionToken();
  //         activeSessions.add(sessionToken);
          
  //         // Set cookie (expires in 7 days)
  //         const cookieExpiry = new Date();
  //         cookieExpiry.setDate(cookieExpiry.getDate() + 7);
          
  //         // Set cookie without HttpOnly so JavaScript can read it for client-side checks
  //         res.setHeader('Set-Cookie', `${SESSION_COOKIE_NAME}=${sessionToken}; Path=/; Expires=${cookieExpiry.toUTCString()}; SameSite=Strict`);
  //         res.writeHead(200, { 'Content-Type': 'application/json' });
  //         res.end(JSON.stringify({ success: true }));
  //       } else {
  //         res.writeHead(401, { 'Content-Type': 'application/json' });
  //         res.end(JSON.stringify({ success: false, error: 'Incorrect password' }));
  //       }
  //     } catch (error) {
  //       res.writeHead(400, { 'Content-Type': 'application/json' });
  //       res.end(JSON.stringify({ success: false, error: 'Invalid request' }));
  //     }
  //   });
  //   return;
  // }

  // // Public pages that don't require authentication
  // const publicPages = ['/wip.html', '/password.html', '/password', '/about.html'];
  // const isPublicPage = publicPages.includes(urlPath) || urlPath === '/';
  
  // // Allow access to public pages without authentication
  // if (isPublicPage) {
  //   // Continue to serve public pages - no redirect needed
  // } else if (!isAuthenticated) {
  //   // Don't redirect API endpoints (they should return 401)
  //   if (urlPath.startsWith('/api/')) {
  //     // API endpoints should return 401, not redirect
  //     res.writeHead(401, { 'Content-Type': 'application/json' });
  //     res.end(JSON.stringify({ error: 'Authentication required' }));
  //     return;
  //   }
    
  //   // Redirect to password page with redirect parameter
  //   res.writeHead(302, { 'Location': `/password.html?redirect=${encodeURIComponent(urlPath)}` });
  //   res.end();
  //   return;
  // }

  // Handle /api/config endpoint (public, for Supabase credentials)
  if (urlPath === '/api/config' && req.method === 'GET') {
    const supabaseUrl = process.env.SUPABASE_URL || '';
    const supabaseAnonKey = process.env.SUPABASE_ANON_KEY || '';
    
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      SUPABASE_URL: supabaseUrl,
      SUPABASE_ANON_KEY: supabaseAnonKey
    }));
    return;
  }

  // Handle API routes (require authentication)
  if (urlPath === '/api/reminders/settings' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => {
      body += chunk.toString();
    });

    req.on('end', async () => {
      try {
        // Parse JSON body
        const parsedBody = body ? JSON.parse(body) : {};

        // Create mock req/res objects for the handler - 
        const mockReq = {
          method: req.method,
          body: parsedBody
        };

        const mockRes = {
          status: (code) => {
            res.statusCode = code;
            return mockRes;
          },
          json: (data) => {
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(data));
          }
        };

        // Call the handler
        await settingsHandler(mockReq, mockRes);
      } catch (error) {
        console.error('Error handling request:', error);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
      }
    });
    return;
  }

  // Serve static files - use urlPath (without query string) for file path
  let filePath = '.' + urlPath;
  
  // Handle root - show wip.html for everyone
  if (filePath === './' || filePath === '/') {
    // filePath = './wip.html';
    filePath = './login.html'
  }

  const extname = String(path.extname(filePath)).toLowerCase();
  const mimeTypes = {
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png'
  };

  const contentType = mimeTypes[extname] || 'application/octet-stream';

  fs.readFile(filePath, (error, content) => {
    if (error) {
      if (error.code === 'ENOENT') {
        res.writeHead(404, { 'Content-Type': 'text/html' });
        res.end('404 - File Not Found', 'utf-8');
      } else {
        res.writeHead(500);
        res.end(`Server Error: ${error.code}`, 'utf-8');
      }
    } else {
      // Inject Supabase credentials into HTML files (skip wip.html and password.html)
      if (extname === '.html' && !filePath.includes('wip.html') && !filePath.includes('password.html')) {
        const supabaseUrl = process.env.SUPABASE_URL || '';
        const supabaseAnonKey = process.env.SUPABASE_ANON_KEY || '';

        let htmlContent = content.toString();

        // Inject credentials as the FIRST script in <head> to ensure it runs first
        const credentialsScript = `
    <script>
      // Supabase credentials injected by server - MUST RUN FIRST
      (function() {
        window.SUPABASE_URL = '${supabaseUrl}';
        window.SUPABASE_ANON_KEY = '${supabaseAnonKey}';
      })();
    </script>`;

        // Insert at the very beginning of <head>, before any other scripts
        if (htmlContent.includes('<head>')) {
          htmlContent = htmlContent.replace('<head>', '<head>' + credentialsScript);
        } else {
          htmlContent = htmlContent.replace('</head>', credentialsScript + '\n  </head>');
        }
        content = Buffer.from(htmlContent, 'utf-8');
      }

      res.writeHead(200, { 'Content-Type': contentType });
      res.end(content, 'utf-8');
    }
  });
});

server.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}/`);
  console.log('Environment variables loaded from .env.local');
});

