"""
database.py — Инициализация БД, CRUD-хелперы, индексы.
"""

import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

import aiosqlite

from config import DB_PATH

log = logging.getLogger("database")

# ─────────────────────────────────────────────
# DDL
# ─────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tracks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    track_hash    TEXT UNIQUE NOT NULL,
    title         TEXT,
    performer     TEXT,
    duration      INTEGER,
    total_requests INTEGER NOT NULL DEFAULT 0,
    unique_users  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_hash TEXT    NOT NULL,
    timestamp  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS playlists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_hash  TEXT    NOT NULL,
    added_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(playlist_id, track_hash)
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_history_user  ON history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_hash  ON history(track_hash);
CREATE INDEX IF NOT EXISTS idx_history_time  ON history(timestamp);
CREATE INDEX IF NOT EXISTS idx_tracks_hash   ON tracks(track_hash);
CREATE INDEX IF NOT EXISTS idx_pl_user       ON playlists(user_id);
CREATE INDEX IF NOT EXISTS idx_plt_playlist  ON playlist_tracks(playlist_id);
"""


# ─────────────────────────────────────────────
# СОЕДИНЕНИЕ
# ─────────────────────────────────────────────

@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    async with get_db() as db:
        await db.executescript(SCHEMA)
        await db.commit()
    log.info("БД инициализирована: %s", DB_PATH)


async def vacuum_db() -> None:
    async with get_db() as db:
        await db.execute("VACUUM")
        await db.commit()
    log.info("VACUUM выполнен.")


# ─────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────

async def upsert_user(telegram_id: int, username: str | None) -> int:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO users(telegram_id, username) VALUES(?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username",
            (telegram_id, username),
        )
        await db.commit()
        async with db.execute(
            "SELECT id FROM users WHERE telegram_id=?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["id"]


async def get_user_id(telegram_id: int) -> int | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM users WHERE telegram_id=?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["id"] if row else None


async def get_user_created_at(telegram_id: int) -> str | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT created_at FROM users WHERE telegram_id=?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["created_at"] if row else None


# ─────────────────────────────────────────────
# TRACKS
# ─────────────────────────────────────────────

async def upsert_track(
    track_hash: str,
    title: str,
    performer: str,
    duration: int,
) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO tracks(track_hash, title, performer, duration, total_requests) "
            "VALUES(?,?,?,?,1) "
            "ON CONFLICT(track_hash) DO UPDATE SET total_requests=total_requests+1",
            (track_hash, title, performer, duration),
        )
        await db.commit()


async def increment_unique_user(track_hash: str, user_id: int) -> None:
    """Считаем уникальных пользователей через историю."""
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM history WHERE user_id=? AND track_hash=?",
            (user_id, track_hash),
        ) as cur:
            row = await cur.fetchone()
        if row["cnt"] == 0:
            await db.execute(
                "UPDATE tracks SET unique_users=unique_users+1 WHERE track_hash=?",
                (track_hash,),
            )
            await db.commit()


async def get_track(track_hash: str) -> dict | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM tracks WHERE track_hash=?", (track_hash,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ─────────────────────────────────────────────
# HISTORY
# ─────────────────────────────────────────────

async def add_history(user_id: int, track_hash: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO history(user_id, track_hash) VALUES(?,?)",
            (user_id, track_hash),
        )
        await db.commit()


async def get_history(user_id: int, limit: int = 50) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT h.track_hash, h.timestamp, t.title, t.performer "
            "FROM history h LEFT JOIN tracks t ON h.track_hash=t.track_hash "
            "WHERE h.user_id=? ORDER BY h.timestamp DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_history_hashes(user_id: int, limit: int = 50) -> list[str]:
    async with get_db() as db:
        async with db.execute(
            "SELECT track_hash FROM history WHERE user_id=? "
            "ORDER BY timestamp DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [r["track_hash"] for r in rows]


async def get_total_listened(user_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM history WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["cnt"]


async def get_favorite_performer(user_id: int) -> str | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT t.performer, COUNT(*) as cnt "
            "FROM history h JOIN tracks t ON h.track_hash=t.track_hash "
            "WHERE h.user_id=? AND t.performer IS NOT NULL "
            "GROUP BY t.performer ORDER BY cnt DESC LIMIT 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return row["performer"] if row else None


# ─────────────────────────────────────────────
# TOP
# ─────────────────────────────────────────────

async def get_top_tracks(limit: int = 10) -> list[dict]:
    """Треки с ≥ TOP_MIN_UNIQUE_USERS уникальных слушателей."""
    from config import TOP_MIN_UNIQUE_USERS
    async with get_db() as db:
        async with db.execute(
            "SELECT track_hash, title, performer, duration, total_requests, unique_users "
            "FROM tracks WHERE unique_users >= ? "
            "ORDER BY total_requests DESC LIMIT ?",
            (TOP_MIN_UNIQUE_USERS, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_trending_tracks(hours: int = 24, limit: int = 10) -> list[dict]:
    """Топ треков за последние N часов."""
    async with get_db() as db:
        async with db.execute(
            "SELECT h.track_hash, t.title, t.performer, COUNT(*) as cnt "
            "FROM history h JOIN tracks t ON h.track_hash=t.track_hash "
            "WHERE h.timestamp >= datetime('now', ? ) "
            "GROUP BY h.track_hash ORDER BY cnt DESC LIMIT ?",
            (f"-{hours} hours", limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# PLAYLISTS
# ─────────────────────────────────────────────

async def create_playlist(user_id: int, name: str) -> int | None:
    from config import MAX_PLAYLISTS_PER_USER
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM playlists WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if row["cnt"] >= MAX_PLAYLISTS_PER_USER:
            return None
        async with db.execute(
            "INSERT INTO playlists(user_id, name) VALUES(?,?)", (user_id, name)
        ) as cur:
            await db.commit()
            return cur.lastrowid


async def get_playlists(user_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT p.id, p.name, COUNT(pt.id) as track_count "
            "FROM playlists p LEFT JOIN playlist_tracks pt ON p.id=pt.playlist_id "
            "WHERE p.user_id=? GROUP BY p.id ORDER BY p.created_at",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_playlist(playlist_id: int, user_id: int) -> dict | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM playlists WHERE id=? AND user_id=?",
            (playlist_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def rename_playlist(playlist_id: int, user_id: int, new_name: str) -> bool:
    async with get_db() as db:
        async with db.execute(
            "UPDATE playlists SET name=? WHERE id=? AND user_id=?",
            (new_name, playlist_id, user_id),
        ) as cur:
            await db.commit()
            return cur.rowcount > 0


async def delete_playlist(playlist_id: int, user_id: int) -> bool:
    async with get_db() as db:
        async with db.execute(
            "DELETE FROM playlists WHERE id=? AND user_id=?",
            (playlist_id, user_id),
        ) as cur:
            await db.commit()
            return cur.rowcount > 0


async def add_track_to_playlist(playlist_id: int, user_id: int, track_hash: str) -> str:
    """Возвращает 'ok' | 'limit' | 'duplicate' | 'not_found'."""
    from config import MAX_TRACKS_PER_PLAYLIST
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM playlists WHERE id=? AND user_id=?",
            (playlist_id, user_id),
        ) as cur:
            if not await cur.fetchone():
                return "not_found"
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM playlist_tracks WHERE playlist_id=?",
            (playlist_id,),
        ) as cur:
            row = await cur.fetchone()
        if row["cnt"] >= MAX_TRACKS_PER_PLAYLIST:
            return "limit"
        try:
            await db.execute(
                "INSERT INTO playlist_tracks(playlist_id, track_hash) VALUES(?,?)",
                (playlist_id, track_hash),
            )
            await db.commit()
            return "ok"
        except aiosqlite.IntegrityError:
            return "duplicate"


async def remove_track_from_playlist(
    playlist_id: int, user_id: int, track_hash: str
) -> bool:
    async with get_db() as db:
        # проверяем принадлежность
        async with db.execute(
            "SELECT id FROM playlists WHERE id=? AND user_id=?",
            (playlist_id, user_id),
        ) as cur:
            if not await cur.fetchone():
                return False
        async with db.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id=? AND track_hash=?",
            (playlist_id, track_hash),
        ) as cur:
            await db.commit()
            return cur.rowcount > 0


async def get_playlist_tracks(playlist_id: int) -> list[dict]:
    async with get_db() as db:
        async with db.execute(
            "SELECT pt.track_hash, t.title, t.performer, t.duration "
            "FROM playlist_tracks pt LEFT JOIN tracks t ON pt.track_hash=t.track_hash "
            "WHERE pt.playlist_id=? ORDER BY pt.added_at",
            (playlist_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────

async def get_playlist_count(user_id: int) -> int:
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as cnt FROM playlists WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["cnt"]


# ─────────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────────

def make_track_hash(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()
