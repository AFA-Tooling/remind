
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Define base paths
# services/shared/settings.py -> services/shared -> services
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SERVICES_DIR = BASE_DIR / "services"
CONFIG_DIR = SERVICES_DIR / "config"

# Load .env.local from project root
# BASE_DIR is project root
load_dotenv(BASE_DIR / ".env.local")

# Config Paths
OAUTH_CLIENT_SECRET_PATH = CONFIG_DIR / "oauth_client_secret.json"
SERVICE_ACCOUNT_PATH = CONFIG_DIR / "service_account.json"
TOKEN_PATH = CONFIG_DIR / "token.json"

# Environment Variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")

# Helper to add services to sys.path if needed
def setup_path():
    if str(SERVICES_DIR) not in sys.path:
        sys.path.append(str(SERVICES_DIR))

# Discord Configuration
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY")
