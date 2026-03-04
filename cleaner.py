"""
cleaner.py — Очистка устаревшего кеша и периодический VACUUM.
"""

import asyncio
import logging
import time
from pathlib import Path

from config import CACHE_DIR, CACHE_TTL_HOURS
from database import vacuum_db

log = logging.getLogger("cleaner")

_VACUUM_INTERVAL_SEC = 24 * 3600  # раз в сутки


def clean_cache_sync() -> int:
    """Удаляет mp3-файлы старше TTL. Возвращает количество удалённых."""
    removed = 0
    now = time.time()
    ttl_sec = CACHE_TTL_HOURS * 3600

    for f in CACHE_DIR.glob("*.mp3"):
        try:
            age = now - f.stat().st_mtime
            if age > ttl_sec:
                f.unlink(missing_ok=True)
                removed += 1
        except OSError as e:
            log.warning("Ошибка при удалении %s: %s", f, e)

    if removed:
        log.info("Очищено %d устаревших файлов кеша.", removed)
    return removed


async def run_periodic_cleaner() -> None:
    """Фоновая задача: чистка кеша каждые 6 часов + VACUUM раз в сутки."""
    clean_interval = 6 * 3600
    last_vacuum = 0.0

    while True:
        await asyncio.sleep(clean_interval)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, clean_cache_sync)
        except Exception as e:
            log.error("Ошибка очистки кеша: %s", e)

        now = time.time()
        if now - last_vacuum >= _VACUUM_INTERVAL_SEC:
            try:
                await vacuum_db()
                last_vacuum = now
            except Exception as e:
                log.error("Ошибка VACUUM: %s", e)
