import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import dotenv from 'dotenv';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load environment variables - use absolute path
const envPath = path.join(__dirname, '.env.local');
dotenv.config({ path: envPath });

// Import the serverless function logic
import settingsHandler from './api/reminders/settings.js';

const PORT = 3000;

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

  // Handle API routes
  if (req.url === '/api/reminders/settings' && req.method === 'POST') {
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

  // Serve static files
  let filePath = '.' + req.url;
  if (filePath === './') {
    // TEMPORARILY: Serve index.html for testing (change back to login.html when done)
    filePath = './index.html';
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
      // Inject Supabase credentials into HTML files
      if (extname === '.html') {
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

