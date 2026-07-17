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

# === Oxeegen AI API ===
OXEEGEN_API_ENDPOINT = os.getenv("OXEEGEN_API_ENDPOINT", "https://inference-04.oxeegen.com/v1")
OXEEGEN_API_KEY = os.getenv("OXEEGEN_API_KEY")
OXEEGEN_MODEL = os.getenv("OXEEGEN_MODEL", "Oxee-flash")

# === ComfyUI-backed image generation ===
COMFYUI_IMAGE_API_ENDPOINT = os.getenv("COMFYUI_IMAGE_API_ENDPOINT", "https://inference.tournayre.ovh/v1")
COMFYUI_IMAGE_API_KEY = os.getenv("COMFYUI_IMAGE_API_KEY") or OXEEGEN_API_KEY
COMFYUI_IMAGE_MODEL = os.getenv("COMFYUI_IMAGE_MODEL", "moodimage")
COMFYUI_IMAGE_QUALITY = os.getenv("COMFYUI_IMAGE_QUALITY", "standard").strip().lower()
COMFYUI_IMAGE_SIZE = os.getenv("COMFYUI_IMAGE_SIZE", "1024x1024")
COMFYUI_IMAGE_EDIT_SIZE = os.getenv("COMFYUI_IMAGE_EDIT_SIZE", "auto")
COMFYUI_IMAGE_STEPS = int(os.getenv("COMFYUI_IMAGE_STEPS", "32"))
COMFYUI_IMAGE_CFG = float(os.getenv("COMFYUI_IMAGE_CFG", "6.0"))
COMFYUI_IMAGE_EDIT_DENOISE = float(os.getenv("COMFYUI_IMAGE_EDIT_DENOISE", "0.35"))
COMFYUI_IMAGE_EDIT_MAX_BYTES = int(os.getenv("COMFYUI_IMAGE_EDIT_MAX_BYTES", str(12 * 1024 * 1024)))
COMFYUI_IMAGE_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_IMAGE_TIMEOUT_SECONDS", "900"))
COMFYUI_IMAGE_PROMPT_ENHANCE_ENABLED = os.getenv(
    "COMFYUI_IMAGE_PROMPT_ENHANCE_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
COMFYUI_IMAGE_NEGATIVE_PROMPT = os.getenv(
    "COMFYUI_IMAGE_NEGATIVE_PROMPT",
    "low quality, blurry, distorted, deformed, bad anatomy, watermark, text artifacts",
)

# === ComfyUI-backed video generation ===
COMFYUI_VIDEO_API_ENDPOINT = os.getenv("COMFYUI_VIDEO_API_ENDPOINT", COMFYUI_IMAGE_API_ENDPOINT)
COMFYUI_VIDEO_API_KEY = os.getenv("COMFYUI_VIDEO_API_KEY") or COMFYUI_IMAGE_API_KEY
COMFYUI_VIDEO_MODEL = os.getenv("COMFYUI_VIDEO_MODEL", "moodvideo")
COMFYUI_VIDEO_TIMEOUT_SECONDS = int(os.getenv("COMFYUI_VIDEO_TIMEOUT_SECONDS", "7200"))
COMFYUI_VIDEO_POLL_SECONDS = float(os.getenv("COMFYUI_VIDEO_POLL_SECONDS", "10"))
COMFYUI_VIDEO_MAX_PROMPT_CHARS = int(os.getenv("COMFYUI_VIDEO_MAX_PROMPT_CHARS", "6000"))
COMFYUI_VIDEO_MAX_IMAGE_BYTES = int(os.getenv("COMFYUI_VIDEO_MAX_IMAGE_BYTES", str(24 * 1024 * 1024)))

# === Moonshine STT (Voice Recording) ===
MOONSHINE_VOICE_CACHE = os.getenv("MOONSHINE_VOICE_CACHE", "/app/data/moonshine_cache")
os.environ["MOONSHINE_VOICE_CACHE"] = MOONSHINE_VOICE_CACHE
