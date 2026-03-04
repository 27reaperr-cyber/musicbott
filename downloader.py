"""
downloader.py — Поиск через YouTube Music (ytmusicapi) + скачивание через yt-dlp.

Поиск: ytmusicapi.search(..., filter="songs")  — треки из YT Music каталога.
Загрузка: yt-dlp по videoId → mp3 192kbps через FFmpeg.
Кеш: ./cache/<videoId>.mp3, TTL 24 часа.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import TypedDict

import yt_dlp
from ytmusicapi import YTMusic

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
# YTMusic клиент
# Без аккаунта = публичный доступ.
# Для аккаунта: положите headers_auth.json рядом с main.py
# ─────────────────────────────────────────────

_AUTH_FILE = Path(__file__).parent / "headers_auth.json"


def _make_ytm() -> YTMusic:
    if _AUTH_FILE.exists():
        return YTMusic(str(_AUTH_FILE))
    return YTMusic()


_ytm = _make_ytm()


# ─────────────────────────────────────────────
# ТИПЫ
# ─────────────────────────────────────────────

class TrackInfo(TypedDict):
    title:      str
    performer:  str
    duration:   int
    file_path:  str
    track_hash: str


# ─────────────────────────────────────────────
# КЕШ
# ─────────────────────────────────────────────

def _cache_path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}.mp3"


def _is_cached(video_id: str) -> bool:
    p = _cache_path(video_id)
    if not p.exists():
        return False
    return (time.time() - p.stat().st_mtime) / 3600 < CACHE_TTL_HOURS


def make_hash(video_id: str) -> str:
    """track_hash == videoId — уже уникален."""
    return video_id


# ─────────────────────────────────────────────
# ПАРСИНГ РЕЗУЛЬТАТОВ ytmusicapi
# ─────────────────────────────────────────────

def _parse_duration(raw) -> int:
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        parts = raw.strip().split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            pass
    return 0


def _parse_result(item: dict) -> dict | None:
    video_id = item.get("videoId")
    if not video_id:
        return None

    title = item.get("title") or "Unknown"
    artists = item.get("artists") or []
    performer = artists[0]["name"] if artists else (item.get("artist") or "Unknown")
    duration = _parse_duration(
        item.get("duration_seconds") or item.get("duration") or 0
    )
    if duration and duration > MAX_DURATION_SEC:
        return None

    return {
        "title":      title,
        "performer":  performer,
        "duration":   duration,
        "video_id":   video_id,
        "track_hash": video_id,
        "url":        f"https://music.youtube.com/watch?v={video_id}",
    }


# ─────────────────────────────────────────────
# СИНХРОННЫЕ ВЫЗОВЫ (executor)
# ─────────────────────────────────────────────

def _sync_search_ytm(query: str, count: int = 5) -> list[dict]:
    global _ytm
    try:
        raw = _ytm.search(query, filter="songs", limit=count + 5)
    except Exception as e:
        log.warning("ytmusicapi search error: %s", e)
        try:
            _ytm = _make_ytm()
        except Exception:
            pass
        return []

    results = []
    for item in raw:
        parsed = _parse_result(item)
        if parsed:
            results.append(parsed)
        if len(results) >= count:
            break
    return results


def _sync_download_ytdlp(video_id: str, out_tmpl: str) -> bool:
    url = f"https://music.youtube.com/watch?v={video_id}"
    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
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
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            ydl.download([url])
            return True
        except yt_dlp.utils.DownloadError as e:
            log.error("yt-dlp download error %s: %s", video_id, e)
            return False


# ─────────────────────────────────────────────
# ПУБЛИЧНЫЙ API
# ─────────────────────────────────────────────

async def search_list(query: str, count: int = 5) -> list[dict]:
    """
    Поиск треков в YouTube Music.
    Возвращает: title, performer, duration, url, track_hash, video_id.
    """
    loop = asyncio.get_event_loop()
    backoff = 2
    for attempt in range(3):
        results = await loop.run_in_executor(None, _sync_search_ytm, query, count)
        if results:
            return results
        log.warning("search_list попытка %d пустая, жду %ds", attempt + 1, backoff)
        await asyncio.sleep(backoff)
        backoff *= 2
    return []


async def download_by_url(
    url: str,
    track_hash: str,
    title: str,
    performer: str,
    duration: int,
) -> TrackInfo | None:
    """Скачивает трек по videoId (track_hash == videoId)."""
    video_id = track_hash

    if _is_cached(video_id):
        log.info("Кеш-хит: %s", video_id)
        return TrackInfo(
            title=title, performer=performer, duration=duration,
            file_path=str(_cache_path(video_id)), track_hash=track_hash,
        )

    async with _semaphore:
        loop = asyncio.get_event_loop()
        out_tmpl = str(CACHE_DIR / f"{video_id}.%(ext)s")

        backoff = 2
        success = False
        for attempt in range(3):
            success = await loop.run_in_executor(
                None, _sync_download_ytdlp, video_id, out_tmpl
            )
            if success:
                break
            log.warning("Попытка %d загрузки не удалась, жду %ds", attempt + 1, backoff)
            await asyncio.sleep(backoff)
            backoff *= 2

        if not success:
            return None

        mp3_path = _cache_path(video_id)
        if not mp3_path.exists():
            log.error("MP3 не найден после загрузки: %s", mp3_path)
            return None

        real_size_mb = mp3_path.stat().st_size / 1024 / 1024
        if real_size_mb > MAX_FILE_SIZE_MB:
            mp3_path.unlink(missing_ok=True)
            log.info("Файл превысил лимит (%.1fMB)", real_size_mb)
            return None

        return TrackInfo(
            title=title, performer=performer, duration=duration,
            file_path=str(mp3_path), track_hash=track_hash,
        )


async def search_and_download(query: str) -> TrackInfo | None:
    """Найти первый трек и сразу скачать (для истории/топа)."""
    results = await search_list(query, count=1)
    if not results:
        return None
    t = results[0]
    return await download_by_url(
        url=t["url"], track_hash=t["track_hash"],
        title=t["title"], performer=t["performer"], duration=t["duration"],
    )
