"""
config.py — Конфигурация бота. Загружает .env, задаёт константы.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent

load_dotenv(BASE_DIR / ".env")

# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
BOT_TOKEN: str = os.environ["BOT_TOKEN"]

# ─────────────────────────────────────────────
# ПУТИ
# ─────────────────────────────────────────────
CACHE_DIR:    Path = BASE_DIR / "cache"
LOGS_DIR:     Path = BASE_DIR / "logs"
FFMPEG_DIR:   Path = BASE_DIR / "ffmpeg_bin"
DB_PATH:      Path = BASE_DIR / "bot.db"

CACHE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
FFMPEG_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# АУДИО
# ─────────────────────────────────────────────
MAX_DURATION_SEC: int   = 600        # 10 минут
MAX_FILE_SIZE_MB: float = 50.0
AUDIO_BITRATE: str      = "192k"
CACHE_TTL_HOURS: int    = 24

# ─────────────────────────────────────────────
# ПЛЕЙЛИСТЫ
# ─────────────────────────────────────────────
MAX_PLAYLISTS_PER_USER: int = 10
MAX_TRACKS_PER_PLAYLIST: int = 200

# ─────────────────────────────────────────────
# АНТИСПАМ / RATE LIMIT
# ─────────────────────────────────────────────
RATE_LIMIT_SECONDS: int  = 5          # 1 запрос / 5 сек
FLOOD_THRESHOLD: int     = 10         # запросов за минуту → mute
FLOOD_MUTE_MINUTES: int  = 10
ERROR_THRESHOLD: int     = 5          # ошибок подряд → блок
DOWNLOAD_SEMAPHORE: int  = 3          # параллельных скачиваний

# ─────────────────────────────────────────────
# ГЛОБАЛЬНЫЙ ТОП
# ─────────────────────────────────────────────
TOP_MIN_UNIQUE_USERS: int = 1000      # порог попадания в топ
TOP_TRENDING_HOURS: int   = 24

# ─────────────────────────────────────────────
# МОЯ ВОЛНА
# ─────────────────────────────────────────────
WAVE_SKIP_LAST: int       = 50        # не повторять последние N треков
WAVE_SIMILAR_RATIO: float = 0.70
WAVE_TREND_RATIO:   float = 0.20
WAVE_RANDOM_RATIO:  float = 0.10
WAVE_POOL_SIZE:     int   = 10        # треков в одной подборке

# ─────────────────────────────────────────────
# ЛОГИРОВАНИЕ
# ─────────────────────────────────────────────
LOG_FILE:  Path = LOGS_DIR / "bot.log"
LOG_LEVEL: str  = os.getenv("LOG_LEVEL", "INFO")
