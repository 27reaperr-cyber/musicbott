"""
top_engine.py — Глобальный топ и trending.
Приватность: хранятся только хеши запросов.
"""

import logging
from database import get_top_tracks, get_trending_tracks
from config import TOP_TRENDING_HOURS

log = logging.getLogger("top_engine")


async def get_global_top(limit: int = 10) -> list[dict]:
    """
    Возвращает треки с >= TOP_MIN_UNIQUE_USERS уникальных слушателей.
    Треки, не достигшие порога, не попадают в топ (приватность).
    """
    return await get_top_tracks(limit)


async def get_trending(limit: int = 10) -> list[dict]:
    """Треки с наибольшим количеством прослушиваний за последние 24 часа."""
    return await get_trending_tracks(hours=TOP_TRENDING_HOURS, limit=limit)


def format_top_list(tracks: list[dict], title: str) -> str:
    if not tracks:
        return f"{title}\n\n<i>Пока пусто — слушайте музыку!</i>"
    lines = [f"{title}\n"]
    for i, t in enumerate(tracks, 1):
        name = t.get("title") or "?"
        perf = t.get("performer") or ""
        cnt = t.get("total_requests") or t.get("cnt") or 0
        lines.append(f"{i}. <b>{perf} — {name}</b>  ·  {cnt}▶")
    return "\n".join(lines)
