Automated reminders for students, powered by a single source of truth.

AutoRemind is a microservice designed to centralize communication with students about their coursework. By integrating with Learning Management Systems (LMS), starting with GradeView, AutoRemind delivers timely, automated messages containing critical course information and direct access to related resources.

Notable Features

1. Automated Messaging: Sends reminders via email or SMS about coursework deadlines, announcements, and updates.

2. Resource Links: Includes a curated list of resources for students to access directly from their messages.

3. LMS Integration: Seamlessly integrates with LMS platforms, beginning with GradeView.

4. Single Source of Truth: Ensures consistency and accuracy by pulling data from a unified backend.

5. API Calls: Utilizes Twilio for SMS notifications and SendGrid for email delivery.

Integration with LMS (GradeView)

AutoRemind will use the GradeView API to fetch and push course-related updates. The system ensures that students receive reminders tailored to their enrolled courses (CS 10 for now). Future updates will include expanded integration with other LMS platforms and courses.

RUN SITE LOCALLY:
- create a .env.local file at root populate with:
    - SUPABASE_URL = https://<project-id>.supabase.co
    - SUPABASE_ANON_KEY = <anon-key>
    - SUPABASE_SERVICE_ROLE_KEY = <service-role-key>

HOW TO GET YOUR SUPABASE CREDENTIALS:

1. Go to https://supabase.com and sign in (or create a free account)
2. Create a new project or select an existing project
3. Once in your project dashboard:
   
   a) SUPABASE_URL:
      - Go to: Project Settings (gear icon in left sidebar) → General
      - Find "Project URL" or "Reference ID"
      - Copy the URL (format: https://xxxxxxxxxxxxx.supabase.co)
      - OR use: https://<project-id>.supabase.co where <project-id> is your Project ID
   
   b) SUPABASE_ANON_KEY:
      - Go to: Project Settings → API Keys
      - Find the "anon" or "public" key
      - Click "Reveal" if needed, then copy it
      - This is safe to expose in client-side code
   
   c) SUPABASE_SERVICE_ROLE_KEY:
      - Go to: Project Settings → API Keys
      - Find the "service_role" or "secret" key
      - Click "Reveal" (you'll need to confirm), then copy it
      - ⚠️ KEEP THIS SECRET - Never expose this in client-side code!

IMPORTANT:
- SUPABASE_ANON_KEY is used for client-side authentication (in HTML/JS)
- SUPABASE_SERVICE_ROLE_KEY is used for server-side operations (in API routes)
- DO NOT commit/push .env.local - IF YOU PUSH IT, GENERATE NEW KEYS

- use `npm run test-server` to run server.js

AUTHENTICATION:
- The app uses Supabase Auth for user authentication
- Users can sign in with Google via login.html
- index.html is protected and requires authentication
- The server automatically injects Supabase credentials into HTML files

GOOGLE OAUTH SETUP:
To enable Google sign-in, you need to configure it in Supabase:
1. Go to your Supabase project dashboard
2. Navigate to: Authentication → Providers
3. Enable "Google" provider
4. Add your Google OAuth credentials:
   - Get Client ID and Client Secret from Google Cloud Console
   - Create OAuth 2.0 credentials at: https://console.cloud.google.com/apis/credentials
   - Add authorized redirect URI: https://<your-project-id>.supabase.co/auth/v1/callback
5. Save the configuration