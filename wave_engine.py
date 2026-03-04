"""
wave_engine.py — «Моя волна»: персонализированная подборка треков.

Алгоритм:
  70% похожие (по исполнителям из истории)
  20% из глобального тренда
  10% случайные (из всех треков в БД)

Не повторяем последние WAVE_SKIP_LAST треков.
"""

import logging
import random
from database import get_db, get_history_hashes, get_trending_tracks
from config import (
    WAVE_SKIP_LAST,
    WAVE_SIMILAR_RATIO,
    WAVE_TREND_RATIO,
    WAVE_RANDOM_RATIO,
    WAVE_POOL_SIZE,
)

log = logging.getLogger("wave_engine")


async def _get_favorite_performers(user_id: int, limit: int = 5) -> list[str]:
    async with get_db() as db:
        async with db.execute(
            "SELECT t.performer, COUNT(*) as cnt "
            "FROM history h JOIN tracks t ON h.track_hash=t.track_hash "
            "WHERE h.user_id=? AND t.performer IS NOT NULL "
            "GROUP BY t.performer ORDER BY cnt DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [r["performer"] for r in rows]


async def _get_similar_tracks(
    performers: list[str], exclude_hashes: set[str], limit: int
) -> list[dict]:
    if not performers:
        return []
    async with get_db() as db:
        placeholders = ",".join("?" * len(performers))
        async with db.execute(
            f"SELECT track_hash, title, performer, duration "
            f"FROM tracks WHERE performer IN ({placeholders}) "
            f"ORDER BY total_requests DESC LIMIT ?",
            (*performers, limit * 3),
        ) as cur:
            rows = await cur.fetchall()
    result = [dict(r) for r in rows if r["track_hash"] not in exclude_hashes]
    return result[:limit]


async def _get_random_tracks(exclude_hashes: set[str], limit: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT track_hash, title, performer, duration FROM tracks "
            "ORDER BY RANDOM() LIMIT ?",
            (limit * 3,),
        ) as cur:
            rows = await cur.fetchall()
    result = [dict(r) for r in rows if r["track_hash"] not in exclude_hashes]
    random.shuffle(result)
    return result[:limit]


async def build_wave(user_id: int) -> list[dict]:
    """Строит персонализированную подборку для пользователя."""
    n_total = WAVE_POOL_SIZE
    n_similar = max(1, int(n_total * WAVE_SIMILAR_RATIO))
    n_trend   = max(1, int(n_total * WAVE_TREND_RATIO))
    n_random  = max(1, n_total - n_similar - n_trend)

    # Исключаем последние N треков
    recent = set(await get_history_hashes(user_id, WAVE_SKIP_LAST))

    # Похожие по исполнителям
    performers = await _get_favorite_performers(user_id)
    similar = await _get_similar_tracks(performers, recent, n_similar)

    # Тренды
    trend_raw = await get_trending_tracks(limit=n_trend * 3)
    trending = [t for t in trend_raw if t.get("track_hash") not in recent][:n_trend]

    # Случайные
    already = recent | {t["track_hash"] for t in similar} | {t.get("track_hash") for t in trending}
    random_tracks = await _get_random_tracks(already, n_random)

    pool = similar + trending + random_tracks
    random.shuffle(pool)

    # Дедупликация
    seen: set[str] = set()
    result: list[dict] = []
    for t in pool:
        h = t.get("track_hash")
        if h and h not in seen:
            seen.add(h)
            result.append(t)
        if len(result) >= n_total:
            break

    log.info(
        "Волна для uid=%d: %d треков (sim=%d, trend=%d, rnd=%d)",
        user_id, len(result), len(similar), len(trending), len(random_tracks),
    )
    return result
