"""
playlists.py — Фасад для работы с плейлистами.
"""

import logging
import database as db

log = logging.getLogger("playlists")


async def create(user_id: int, name: str) -> int | None:
    """Возвращает id созданного плейлиста или None (превышен лимит)."""
    return await db.create_playlist(user_id, name.strip()[:64])


async def list_playlists(user_id: int) -> list[dict]:
    return await db.get_playlists(user_id)


async def get(pl_id: int, user_id: int) -> dict | None:
    return await db.get_playlist(pl_id, user_id)


async def rename(pl_id: int, user_id: int, new_name: str) -> bool:
    return await db.rename_playlist(pl_id, user_id, new_name.strip()[:64])


async def delete(pl_id: int, user_id: int) -> bool:
    return await db.delete_playlist(pl_id, user_id)


async def add_track(pl_id: int, user_id: int, track_hash: str) -> str:
    return await db.add_track_to_playlist(pl_id, user_id, track_hash)


async def remove_track(pl_id: int, user_id: int, track_hash: str) -> bool:
    return await db.remove_track_from_playlist(pl_id, user_id, track_hash)


async def get_tracks(pl_id: int) -> list[dict]:
    return await db.get_playlist_tracks(pl_id)
