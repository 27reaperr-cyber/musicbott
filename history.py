"""
history.py — Работа с историей прослушиваний.
"""

import logging
from database import add_history, get_history, get_history_hashes

log = logging.getLogger("history")


async def record_play(user_id: int, track_hash: str) -> None:
    await add_history(user_id, track_hash)


async def get_user_history(user_id: int, limit: int = 50) -> list[dict]:
    return await get_history(user_id, limit)


async def get_recent_hashes(user_id: int, limit: int = 50) -> list[str]:
    return await get_history_hashes(user_id, limit)
