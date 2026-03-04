"""
downloader.py — Поиск и скачивание треков через yt-dlp.
Кеш на диске, хеш по запросу, TTL 24 часа.
"""

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import TypedDict

import yt_dlp

from config import (
    AUDIO_BITRATE,
    CACHE_DIR,
    CACHE_TTL_HOURS,
    DOWNLOAD_SEMAPHORE,
    MAX_DURATION_SEC,
    MAX_FILE_SIZE_MB,
)

log = logging.getLogger("downloader")

_semaphore = asyncio.Semaphore(DOWNLOAD_SEMAPHORE)

# ─────────────────────────────────────────────

class TrackInfo(TypedDict):
    title: str
    performer: str
    duration: int
    file_path: str
    track_hash: str


# ─────────────────────────────────────────────
# КЕШ
# ─────────────────────────────────────────────

def _cache_path(track_hash: str) -> Path:
    return CACHE_DIR / f"{track_hash}.mp3"


def _is_cached(track_hash: str) -> bool:
    p = _cache_path(track_hash)
    if not p.exists():
        return False
    age_hours = (time.time() - p.stat().st_mtime) / 3600
    return age_hours < CACHE_TTL_HOURS


def make_hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


# ─────────────────────────────────────────────
# ПОИСК + ЗАГРУЗКА
# ─────────────────────────────────────────────

def _ydl_opts(output_path: str) -> dict:
    return {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": AUDIO_BITRATE.rstrip("k"),
            }
        ],
        "socket_timeout": 30,
        "retries": 3,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        },
    }


def _sync_extract_info(query: str) -> dict | None:
    """Синхронный вызов yt-dlp для получения метаданных."""
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        except yt_dlp.utils.DownloadError as e:
            log.warning("yt-dlp extract_info error: %s", e)
            return None

    if not info:
        return None
    entries = info.get("entries")
    if entries:
        return entries[0] if entries else None
    return info


def _sync_download(url: str, out_tmpl: str) -> bool:
    """Синхронная загрузка через yt-dlp."""
    opts = _ydl_opts(out_tmpl)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            ydl.download([url])
            return True
        except yt_dlp.utils.DownloadError as e:
            log.error("yt-dlp download error: %s", e)
            return False


# ─────────────────────────────────────────────
# ПУБЛИЧНЫЙ API
# ─────────────────────────────────────────────

async def search_and_download(query: str) -> TrackInfo | None:
    """
    Ищет трек, скачивает mp3, возвращает TrackInfo.
    Возвращает None при любой ошибке или превышении лимитов.
    """
    track_hash = make_hash(query)

    # Проверяем кеш
    if _is_cached(track_hash):
        log.info("Кеш-хит: %s", track_hash[:8])
        # Получаем мета из yt-dlp (быстро, без скачивания)
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _sync_extract_info, query)
        if info:
            return TrackInfo(
                title=info.get("title", "Unknown"),
                performer=info.get("uploader", info.get("artist", "Unknown")),
                duration=int(info.get("duration") or 0),
                file_path=str(_cache_path(track_hash)),
                track_hash=track_hash,
            )
        # fallback: просто вернём файл без мета
        return TrackInfo(
            title="Unknown",
            performer="Unknown",
            duration=0,
            file_path=str(_cache_path(track_hash)),
            track_hash=track_hash,
        )

    async with _semaphore:
        return await _fetch(query, track_hash)


async def _fetch(query: str, track_hash: str) -> TrackInfo | None:
    """Основной пайплайн: инфо → валидация → скачивание."""
    loop = asyncio.get_event_loop()

    # 1. Получаем метаданные
    backoff = 2
    info = None
    for attempt in range(3):
        info = await loop.run_in_executor(None, _sync_extract_info, query)
        if info:
            break
        log.warning("Попытка %d не дала результата, ожидаю %ds", attempt + 1, backoff)
        await asyncio.sleep(backoff)
        backoff *= 2

    if not info:
        log.error("Трек не найден: %s", query)
        return None

    # 2. Валидация длительности
    duration = int(info.get("duration") or 0)
    if duration > MAX_DURATION_SEC:
        log.info("Трек слишком длинный (%ds): %s", duration, query)
        return None

    # 3. Валидация размера (приблизительно)
    filesize = info.get("filesize") or info.get("filesize_approx") or 0
    if filesize and filesize > MAX_FILE_SIZE_MB * 1024 * 1024:
        log.info("Трек слишком большой (%.1fMB): %s", filesize / 1024 / 1024, query)
        return None

    # 4. Скачиваем
    url = info.get("webpage_url") or info.get("url", "")
    out_tmpl = str(CACHE_DIR / f"{track_hash}.%(ext)s")

    success = await loop.run_in_executor(None, _sync_download, url, out_tmpl)
    if not success:
        return None

    mp3_path = _cache_path(track_hash)
    if not mp3_path.exists():
        log.error("MP3 файл не найден после загрузки: %s", mp3_path)
        return None

    # 5. Финальная проверка размера
    real_size_mb = mp3_path.stat().st_size / 1024 / 1024
    if real_size_mb > MAX_FILE_SIZE_MB:
        mp3_path.unlink(missing_ok=True)
        log.info("Готовый файл превысил лимит (%.1fMB)", real_size_mb)
        return None

    title = info.get("title", "Unknown")
    performer = (
        info.get("artist")
        or info.get("uploader")
        or info.get("channel")
        or "Unknown"
    )

    return TrackInfo(
        title=title,
        performer=performer,
        duration=duration,
        file_path=str(mp3_path),
        track_hash=track_hash,
    )
