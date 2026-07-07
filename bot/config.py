"""
SKORMAgency - Configuration
Loads environment variables and defines SKORM branding constants.
"""
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# === Bot credentials ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
SERVER_ID = int(os.getenv("SERVER_ID", "0")) if os.getenv("SERVER_ID") else None
OWNER_ID = int(os.getenv("OWNER_ID", "0")) if os.getenv("OWNER_ID") else None

# === SKORM brand colors (black/white/gray minimalist palette) ===
COLOR_WHITE = 0xFFFFFF
COLOR_LIGHT_GRAY = 0xAAAAAA
COLOR_GRAY = 0x888888
COLOR_MED_GRAY = 0x555555
COLOR_DARK_GRAY = 0x333333
COLOR_BLACK = 0x000000

# Default embed color
EMBED_COLOR = COLOR_BLACK

# === Assets ===
ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"
)
LOGO_PATH = os.path.join(ASSETS_DIR, "skormlogo.jpeg")
BANNER_PATH = os.path.join(ASSETS_DIR, "skormban.jpeg")

# === Database ===
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
DB_PATH = os.path.join(DATA_DIR, "skorm.db")

# === Branding ===
BRAND_NAME = "SKORM"
BRAND_TAGLINE = "CREATE. CONNECT. DEVELOP."
FOOTER_TEXT = "SKORM — CREATE. CONNECT. DEVELOP."

# === Lavalink (Music) ===
LAVALINK_HOST = os.getenv("LAVALINK_HOST", "lavalink")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "skorm")