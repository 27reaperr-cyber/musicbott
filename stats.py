"""
stats.py — Пользовательская статистика.
"""

import logging
from datetime import datetime

from database import (
    get_total_listened,
    get_favorite_performer,
    get_playlist_count,
    get_user_created_at,
)

log = logging.getLogger("stats")


async def get_user_stats(telegram_id: int, user_id: int) -> dict:
    total = await get_total_listened(user_id)
    fav_performer = await get_favorite_performer(user_id)
    pl_count = await get_playlist_count(user_id)
    created_at_str = await get_user_created_at(telegram_id)

    days_with_bot = 0
    if created_at_str:
        try:
            created = datetime.fromisoformat(created_at_str)
            days_with_bot = (datetime.utcnow() - created).days
        except ValueError:
            pass

    return {
        "total_listened": total,
        "favorite_performer": fav_performer or "—",
        "playlist_count": pl_count,
        "days_with_bot": days_with_bot,
    }


def format_stats(stats: dict) -> str:
    return (
        "📊 <b>Ваша статистика</b>\n\n"
        f"🎵 Всего прослушано: <b>{stats['total_listened']}</b>\n"
        f"🎤 Любимый исполнитель: <b>{stats['favorite_performer']}</b>\n"
        f"🎼 Плейлистов: <b>{stats['playlist_count']}</b>\n"
        f"📅 Дней с ботом: <b>{stats['days_with_bot']}</b>"
    )
