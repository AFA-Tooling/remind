
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

# Firebase Configuration
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
# Path to a Firebase-enabled service account JSON.
# Defaults to the existing service_account.json used for Google Sheets.
_sa_env = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
FIREBASE_SERVICE_ACCOUNT_PATH = Path(_sa_env) if _sa_env else SERVICE_ACCOUNT_PATH

# Local Firestore emulator (see docs/local-testing.md).
# Put USE_FIRESTORE_EMULATOR=true in your local .env.local and every script that
# imports this module talks to the emulator instead of production, even in a
# terminal where you forgot to set FIRESTORE_EMULATOR_HOST. The Firestore SDKs
# read FIRESTORE_EMULATOR_HOST when the client is created, so setting it here
# (at import time, before any client exists) is enough. If the emulator isn't
# running, scripts fail to connect rather than falling through to production.
# Deploys never set this flag: the deploy scripts copy only named keys out of
# .env.local, and .env.local itself is excluded from the Cloud images.
DEFAULT_FIRESTORE_EMULATOR_HOST = "127.0.0.1:8080"
USE_FIRESTORE_EMULATOR = os.getenv("USE_FIRESTORE_EMULATOR", "").strip().lower() in ("1", "true", "yes")
if USE_FIRESTORE_EMULATOR and not os.getenv("FIRESTORE_EMULATOR_HOST"):
    os.environ["FIRESTORE_EMULATOR_HOST"] = DEFAULT_FIRESTORE_EMULATOR_HOST
FIRESTORE_EMULATOR_HOST = os.getenv("FIRESTORE_EMULATOR_HOST") or None


def refuse_if_emulator(action: str) -> None:
    """Exit before an action with real-world side effects runs against emulator data.

    Emulator data can contain real student contact info (gradesync_to_db.py copies
    the real rosters in), so sending messages from it would reach real students.
    """
    if FIRESTORE_EMULATOR_HOST:
        sys.exit(
            f"Refusing to {action}: Firestore emulator mode is on "
            f"(FIRESTORE_EMULATOR_HOST={FIRESTORE_EMULATOR_HOST}). "
            "Emulator runs are for generating and inspecting CSVs only."
        )


def require_emulator(action: str) -> str:
    """Exit unless Firestore points at a local emulator. Returns the emulator host."""
    host = FIRESTORE_EMULATOR_HOST or ""
    hostname = host.rsplit(":", 1)[0].strip("[]")
    if hostname not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        sys.exit(
            f"Refusing to {action}: this only runs against a local Firestore emulator. "
            "Set USE_FIRESTORE_EMULATOR=true in .env.local (or FIRESTORE_EMULATOR_HOST) "
            "and start it with `npm run emulator`."
        )
    return host

# Student-facing dashboard. Linked from every reminder email so students who were
# auto-enrolled at consent time know where to change their preferences.
AUTOREMIND_SITE_URL = os.getenv("AUTOREMIND_SITE_URL", "https://autoremind.eecs.berkeley.edu")

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

# Canvas LMS Configuration
CANVAS_CLIENT_ID = os.getenv("CANVAS_CLIENT_ID")
CANVAS_CLIENT_SECRET = os.getenv("CANVAS_CLIENT_SECRET")
CANVAS_DEFAULT_DOMAIN = os.getenv("CANVAS_DEFAULT_DOMAIN", "bcourses.berkeley.edu")
