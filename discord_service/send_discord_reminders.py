import os, requests, time, csv
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID  = os.getenv("DISCORD_GUILD_ID") 

BASE = "https://discord.com/api/v10"
HEADERS = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}

BASE_DIR = Path(__file__).resolve().parent
env_csv = os.getenv("DISCORD_CSV_FOLDER")
if env_csv:
    CSV_FOLDER = Path(env_csv)
else:
    CSV_FOLDER = BASE_DIR / "message_requests"
# CSV_FOLDER = Path(os.getenv("DISCORD_CSV_FOLDER", r"discord_service\message_requests"))

def get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    if r.status_code == 429:
        time.sleep(float(r.json().get("retry_after", 1.0)))
        return get(url, params)
    r.raise_for_status()
    return r.json()


def post(url, json, retries=0):
    MAX_RETRIES = 3
    r = requests.post(url, headers=HEADERS, json=json, timeout=15)
    
    if r.status_code == 429:
        if retries >= MAX_RETRIES:
            print(f"❌ Hit max retries ({MAX_RETRIES}) for rate limiting. Giving up.")
            r.raise_for_status()

        retry_after = float(r.json().get('retry_after', 1.0))
        print(f"Rate limited. Sleeping for {retry_after}s... (Attempt {retries+1}/{MAX_RETRIES})")
        time.sleep(retry_after)
        return post(url, json, retries=retries + 1)
    
    if r.status_code >= 400:
        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text}
        # Print Discord's error code & message for quick diagnosis
        print("HTTP", r.status_code, err)
        r.raise_for_status()
    return r.json()

def find_member_by_username(guild_id: str, username: str):
    """
    Search the guild for an exact username match (new Discord usernames are unique).
    NOTE: /members/search matches prefixes; we still filter to exact username.
    return a member object (dict)
    """
    candidates = get(
        f"{BASE}/guilds/{guild_id}/members/search",
        params={"query": username, "limit": 100}
    )
    # exact match on username (case-insensitive just in case)
    uname_lower = username.lower()
    for m in candidates:
        if m["user"].get("username", "").lower() == uname_lower:
            return m
    return None  # not found


def open_dm(user_id: str) -> str:
    """
    returns a channal id 
    """
    resp = post(f"{BASE}/users/@me/channels", {"recipient_id": str(user_id)})
    return resp["id"]

def send_dm(channel_id: str, content: str):
    """
    send the dm
    """
    post(f"{BASE}/channels/{channel_id}/messages", {
        "content": content,
        "allowed_mentions": {"parse": []}
    })

def dm_by_username(guild_id: str, username: str, message: str):
    member = find_member_by_username(guild_id, username)
    if not member:
        raise ValueError(f"User '{username}' not found in guild {guild_id}.")
    user_id = member["user"]["id"]
    ch_id = open_dm(user_id)
    send_dm(ch_id, message)
    print(f"DM sent to {username} (id={user_id})")

def parse_csv_to_dict(file_path):
    """
    input: a Path to a CSV in the message_requests folder
    return: a dictionary {discord_id: message}
    """
    dict = {}
    with file_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return dict

        # New: use the named columns directly
        for row in reader:
            discord_id = (row.get("discord_id") or "").strip()
            message = (row.get("message") or "").strip()
            if not discord_id or not message:
                continue
            dict[discord_id] = message
    return dict

def dm_to_all():
    if not CSV_FOLDER.exists() or not CSV_FOLDER.is_dir():
        raise FileNotFoundError(f"CSV folder not found or not a directory: {CSV_FOLDER}")

    # for each csv:
    for csv_path in CSV_FOLDER.glob("*.csv"):
        print(f"\n=== Processing {csv_path.name} ===")
        dict_of_message = parse_csv_to_dict(csv_path)

        for username, message in dict_of_message.items():
            if not message:
                continue
            try:
                dm_by_username(GUILD_ID, username, message)
            except Exception as e:
                # This catches ValueErrors (User not found) 
                # AND requests.exceptions.HTTPError (Cannot send to user/Blocked bot)
                print(f"⚠️ Failed to send to '{username}'. Reason: {e}")
            time.sleep(0.5)


if __name__ == "__main__":
    dm_to_all()