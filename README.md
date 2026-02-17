# AutoRemind

**Automated reminders for students, powered by a single source of truth.**

AutoRemind is a modular notification system that integrates with Grade Sources (like Google Sheets) and Learning Management Systems to send automated, personalized reminders via Email, Discord, and SMS.

## Documentation

Comprehensive documentation is available in the `docs/` directory:

- **[System Overview](docs/system_overview.md)**: Architecture and high-level design.
- **[Deployment Guide](docs/deployment.md)**: How to deploy to Google Cloud Platform.
- **Services**:
  - [Email Service](docs/services/email-service.md)
  - [GradeSync Service](docs/services/gradesync-service.md) (Data Ingestion)
  - [Discord Service](docs/services/discord-service.md)
  - [Text Service](docs/services/text-service.md)

## Quick Start

### 1. Setup

```bash
# Install Python dependencies for all services
pip install -r services/requirements.txt

# Install Node.js dependencies for the web dashboard
npm install
```

### 2. Configuration

Copy the example environment file and fill in your credentials in the **project root**:

```bash
cp .env.example .env.local
# Edit .env.local with your keys (Supabase, Google, Twilio, Discord)
```

**Important**: Do not create `.env` files inside individual service directories. The system only reads from the root `.env.local`.

### 3. Run Locally

**Backend Server (Web Dashboard)**
```bash
npm run dev
```

**Microservices**
Refer to the individual service documentation in `docs/services/` for running specific pipelines.

## Project Structure

- **`public/`**: Frontend assets (HTML/CSS/JS).
- **`src/`**: Node.js backend server.
- **`services/`**: Python microservices.
- **`docs/`**: Project documentation.