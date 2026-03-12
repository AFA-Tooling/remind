import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import dotenv from 'dotenv';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load environment variables - use absolute path
// Since server.js is now in src/, we look for .env.local in the parent directory
const envPath = path.join(__dirname, '../.env.local');
dotenv.config({ path: envPath });

// Import the serverless function logic
import settingsHandler from './api/reminders/settings.js';
import getHandler from './api/reminders/get.js';
import registerHandler from './api/reminders/register.js';

// Use PORT from environment variable (GCP Cloud Run sets this) or default to 3000 for local dev
const PORT = process.env.PORT || 3000;

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

  // Handle /api/config endpoint (public, for Firebase client credentials)
  if (urlPath === '/api/config' && req.method === 'GET') {
    const firebaseApiKey = process.env.FIREBASE_API_KEY || '';
    const firebaseAuthDomain = process.env.FIREBASE_AUTH_DOMAIN || '';
    const firebaseProjectId = process.env.FIREBASE_PROJECT_ID || '';

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      FIREBASE_API_KEY: firebaseApiKey,
      FIREBASE_AUTH_DOMAIN: firebaseAuthDomain,
      FIREBASE_PROJECT_ID: firebaseProjectId,
    }));
    return;
  }

  // Handle API routes
  if (urlPath === '/api/reminders/get' && req.method === 'GET') {
    // Parse query string from original URL
    const queryParams = {};
    if (queryString) {
      queryString.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key && value) {
          queryParams[decodeURIComponent(key)] = decodeURIComponent(value);
        }
      });
    }

    // Create mock req/res objects for the handler
    const mockReq = {
      method: req.method,
      query: queryParams
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

    try {
      // Call the handler
      await getHandler(mockReq, mockRes);
    } catch (error) {
      console.error('Error handling GET request:', error);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
    }
    return;
  }

  if (urlPath === '/api/reminders/register' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk.toString(); });
    req.on('end', async () => {
      try {
        const mockReq = { method: req.method, body: body ? JSON.parse(body) : {} };
        const mockRes = {
          status: (code) => { res.statusCode = code; return mockRes; },
          json: (data) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); }
        };
        await registerHandler(mockReq, mockRes);
      } catch (error) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
      }
    });
    return;
  }

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

  // Handle /api/reminders/unsubscribe
  if (urlPath === '/api/reminders/unsubscribe' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => {
      body += chunk.toString();
    });

    req.on('end', async () => {
      try {
        const { default: unsubscribeHandler } = await import('./api/reminders/unsubscribe.js');

        const parsedBody = body ? JSON.parse(body) : {};

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

        await unsubscribeHandler(mockReq, mockRes);
      } catch (error) {
        console.error('Error handling unsubscribe:', error);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
      }
    });
    return;
  }

  // Serve static files - use urlPath (without query string) for file path
  // Since server.js is in src/, static files are in ../public/
  let filePath = path.join(__dirname, '../public', urlPath);

  // Handle root - default to index.html (Landing Page)
  if (urlPath === '/' || urlPath === '/index.html') {
    if (urlPath === '/') filePath = path.join(__dirname, '../public/index.html');
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
      // Inject Firebase credentials into HTML files
      if (extname === '.html') {
        const firebaseApiKey = process.env.FIREBASE_API_KEY || '';
        const firebaseAuthDomain = process.env.FIREBASE_AUTH_DOMAIN || '';
        const firebaseProjectId = process.env.FIREBASE_PROJECT_ID || '';

        let htmlContent = content.toString();

        // Inject credentials as the FIRST script in <head> to ensure it runs first
        const credentialsScript = `
    <script>
      // Firebase credentials injected by server - MUST RUN FIRST
      (function() {
        window.FIREBASE_API_KEY = '${firebaseApiKey}';
        window.FIREBASE_AUTH_DOMAIN = '${firebaseAuthDomain}';
        window.FIREBASE_PROJECT_ID = '${firebaseProjectId}';
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