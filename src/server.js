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
import deadlinesGetHandler from './api/deadlines/get.js';
import resourcesGetHandler from './api/resources/get.js';

// Canvas integration handlers
import canvasAuthHandler from './api/canvas/auth.js';
import canvasCallbackHandler from './api/canvas/callback.js';
import canvasDisconnectHandler from './api/canvas/disconnect.js';
import canvasSyncHandler from './api/canvas/sync.js';
import canvasDeadlinesHandler from './api/canvas/deadlines.js';

// Admin handlers
import adminStudentsHandler from './api/admin/students.js';
import adminDeadlinesHandler from './api/admin/deadlines.js';
import adminResourcesHandler from './api/admin/resources.js';
import adminDeliveryLogsHandler from './api/admin/delivery-logs.js';

// Use PORT from environment variable (GCP Cloud Run sets this) or default to 3000 for local dev
const PORT = process.env.PORT || 3000;

const server = http.createServer(async (req, res) => {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

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

  // Handle /api/deadlines
  if (urlPath === '/api/deadlines' && req.method === 'GET') {
    const queryParams = {};
    if (queryString) {
      queryString.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key && value) queryParams[decodeURIComponent(key)] = decodeURIComponent(value);
      });
    }
    const mockReq = { method: req.method, query: queryParams };
    const mockRes = {
      status: (code) => { res.statusCode = code; return mockRes; },
      json: (data) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); }
    };
    try {
      await deadlinesGetHandler(mockReq, mockRes);
    } catch (error) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
    }
    return;
  }

  // Handle /api/resources
  if (urlPath === '/api/resources' && req.method === 'GET') {
    const queryParams = {};
    if (queryString) {
      queryString.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key && value) queryParams[decodeURIComponent(key)] = decodeURIComponent(value);
      });
    }
    const mockReq = { method: req.method, query: queryParams };
    const mockRes = {
      status: (code) => { res.statusCode = code; return mockRes; },
      json: (data) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); }
    };
    try {
      await resourcesGetHandler(mockReq, mockRes);
    } catch (error) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
    }
    return;
  }

  // Helper to parse query params
  const parseQuery = (qs) => {
    const params = {};
    if (qs) {
      qs.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key && value) params[decodeURIComponent(key)] = decodeURIComponent(value);
      });
    }
    return params;
  };

  // Helper to create mock response
  const createMockRes = () => ({
    status: (code) => { res.statusCode = code; return createMockRes(); },
    json: (data) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); }
  });

  // Admin API routes
  if (urlPath.startsWith('/api/admin/')) {
    const mockRes = createMockRes();
    const queryParams = parseQuery(queryString);

    // Parse body for POST/PUT/DELETE
    const parseBody = () => new Promise((resolve) => {
      let body = '';
      req.on('data', chunk => body += chunk.toString());
      req.on('end', () => resolve(body ? JSON.parse(body) : {}));
    });

    try {
      if (urlPath === '/api/admin/students' && req.method === 'GET') {
        const mockReq = { method: req.method, query: queryParams, headers: { authorization: req.headers.authorization } };
        await adminStudentsHandler(mockReq, mockRes);
        return;
      }

      if (urlPath === '/api/admin/deadlines' && req.method === 'GET') {
        const mockReq = { method: req.method, query: queryParams, headers: { authorization: req.headers.authorization } };
        await adminDeadlinesHandler(mockReq, mockRes);
        return;
      }

      if (urlPath === '/api/admin/resources') {
        const body = ['POST', 'PUT', 'DELETE'].includes(req.method) ? await parseBody() : {};
        const mockReq = { method: req.method, query: queryParams, body, headers: { authorization: req.headers.authorization } };
        await adminResourcesHandler(mockReq, mockRes);
        return;
      }

      if (urlPath === '/api/admin/delivery-logs' && req.method === 'GET') {
        const mockReq = { method: req.method, query: queryParams, headers: { authorization: req.headers.authorization } };
        await adminDeliveryLogsHandler(mockReq, mockRes);
        return;
      }
    } catch (error) {
      console.error('Admin API error:', error);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
      return;
    }
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

  // ---- Canvas Integration Routes ----

  // Helper to build mock req/res with redirect support
  const mockRes = {
    status: (code) => { res.statusCode = code; return mockRes; },
    json: (data) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); },
    redirect: (code, url) => { res.writeHead(code, { Location: url }); res.end(); },
  };

  // GET /api/canvas/auth - Initiate Canvas OAuth
  if (urlPath === '/api/canvas/auth' && req.method === 'GET') {
    const queryParams = {};
    if (queryString) {
      queryString.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key && value) queryParams[decodeURIComponent(key)] = decodeURIComponent(value);
      });
    }
    try {
      await canvasAuthHandler({ method: req.method, query: queryParams }, mockRes);
    } catch (error) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
    }
    return;
  }

  // GET /api/canvas/callback - Canvas OAuth callback
  if (urlPath === '/api/canvas/callback' && req.method === 'GET') {
    const queryParams = {};
    if (queryString) {
      queryString.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key && value) queryParams[decodeURIComponent(key)] = decodeURIComponent(value);
      });
    }
    try {
      await canvasCallbackHandler({ method: req.method, query: queryParams }, mockRes);
    } catch (error) {
      console.error('Canvas callback error:', error);
      res.writeHead(302, { Location: `/index.html?canvas=error&reason=${encodeURIComponent(error.message)}` });
      res.end();
    }
    return;
  }

  // POST /api/canvas/disconnect
  if (urlPath === '/api/canvas/disconnect' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk.toString(); });
    req.on('end', async () => {
      try {
        await canvasDisconnectHandler({ method: req.method, body: body ? JSON.parse(body) : {} }, mockRes);
      } catch (error) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
      }
    });
    return;
  }

  // POST /api/canvas/sync
  if (urlPath === '/api/canvas/sync' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk.toString(); });
    req.on('end', async () => {
      try {
        await canvasSyncHandler({ method: req.method, body: body ? JSON.parse(body) : {} }, mockRes);
      } catch (error) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
      }
    });
    return;
  }

  // GET /api/canvas/deadlines
  if (urlPath === '/api/canvas/deadlines' && req.method === 'GET') {
    const queryParams = {};
    if (queryString) {
      queryString.split('&').forEach(param => {
        const [key, value] = param.split('=');
        if (key && value) queryParams[decodeURIComponent(key)] = decodeURIComponent(value);
      });
    }
    try {
      await canvasDeadlinesHandler({ method: req.method, query: queryParams }, mockRes);
    } catch (error) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Internal server error', details: error.message }));
    }
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