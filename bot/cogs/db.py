"""
SKORMAgency - Database helper
Initialises the SQLite database and exposes aiosqlite connection helpers.
"""
import os
from datetime import datetime

import aiosqlite

from bot.config import DATA_DIR, DB_PATH


# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    channel_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    claimed_by INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    remind_at TIMESTAMP NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    moderator_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    event_time TIMESTAMP NOT NULL,
    notified_24h INTEGER NOT NULL DEFAULT 0,
    notified_1h INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS music_state (
    guild_id INTEGER PRIMARY KEY,
    current_track_data TEXT,
    current_position INTEGER NOT NULL DEFAULT 0,
    is_paused INTEGER NOT NULL DEFAULT 0,
    volume INTEGER NOT NULL DEFAULT 100,
    voice_channel_id INTEGER,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS music_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    track_data TEXT NOT NULL,
    FOREIGN KEY (guild_id) REFERENCES music_state(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS music_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    track_data TEXT NOT NULL,
    FOREIGN KEY (guild_id) REFERENCES music_state(guild_id) ON DELETE CASCADE
);
"""


async def init_db() -> None:
    """Initialise the SQLite schema."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def get_db():
    """Context manager yielding an aiosqlite connection."""
    return aiosqlite.connect(DB_PATH)


# === Tickets ===
async def create_ticket(creator_id: int, channel_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO tickets (creator_id, channel_id, status, created_at) "
            "VALUES (?, ?, 'open', ?)",
            (creator_id, channel_id, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def close_ticket(ticket_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET status='closed', closed_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), ticket_id),
        )
        await db.commit()


async def claim_ticket(ticket_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET claimed_by=? WHERE id=? AND claimed_by IS NULL",
            (user_id, ticket_id),
        )
        await db.commit()


async def get_ticket_by_channel(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tickets WHERE channel_id=? ORDER BY id DESC LIMIT 1",
            (channel_id,),
        )
        return await cursor.fetchone()


# === Reminders ===
async def add_reminder(user_id: int, message: str, remind_at: datetime) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO reminders (user_id, message, remind_at) VALUES (?, ?, ?)",
            (user_id, message, remind_at.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_due_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE done=0 AND remind_at<=?",
            (datetime.utcnow().isoformat(),),
        )
        return await cursor.fetchall()


async def mark_reminder_done(reminder_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reminders SET done=1 WHERE id=?", (reminder_id,))
        await db.commit()


async def list_active_reminders(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE user_id=? AND done=0 ORDER BY remind_at ASC",
            (user_id,),
        )
        return await cursor.fetchall()


async def delete_reminder(reminder_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM reminders WHERE id=? AND user_id=?",
            (reminder_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


# === Warnings ===
async def add_warning(user_id: int, reason: str, moderator_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO warnings (user_id, reason, moderator_id) VALUES (?, ?, ?)",
            (user_id, reason, moderator_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_warnings(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM warnings WHERE user_id=? ORDER BY timestamp DESC",
            (user_id,),
        )
        return await cursor.fetchall()


async def count_warnings(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM warnings WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


# === Events ===
async def add_event(name: str, event_time: datetime) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO events (name, event_time) VALUES (?, ?)",
            (name, event_time.isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_upcoming_events():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM events WHERE event_time>=? ORDER BY event_time ASC",
            (datetime.utcnow().isoformat(),),
        )
        return await cursor.fetchall()


async def mark_event_notified(event_id: int, kind: str) -> None:
    field = "notified_24h" if kind == "24h" else "notified_1h"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE events SET {field}=1 WHERE id=?", (event_id,))
        await db.commit()


# === Music State Persistence ===
async def save_music_state(guild_id: int, current_track_data: str | None, position: int, is_paused: bool, volume: int, voice_channel_id: int | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO music_state (guild_id, current_track_data, current_position, is_paused, volume, voice_channel_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, current_track_data, position, int(is_paused), volume, voice_channel_id, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_music_state(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM music_state WHERE guild_id=?", (guild_id,))
        return await cursor.fetchone()


async def delete_music_state(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM music_state WHERE guild_id=?", (guild_id,))
        await db.commit()


async def save_music_queue(guild_id: int, queue_data: list) -> None:
    """Save entire queue. queue_data is list of dicts with track info."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM music_queue WHERE guild_id=?", (guild_id,))
        for i, track in enumerate(queue_data, start=1):
            await db.execute(
                "INSERT INTO music_queue (guild_id, position, track_data) VALUES (?, ?, ?)",
                (guild_id, i, track),
            )
        await db.commit()


async def get_music_queue(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM music_queue WHERE guild_id=? ORDER BY position ASC",
            (guild_id,),
        )
        return await cursor.fetchall()


async def save_music_history(guild_id: int, history_data: list) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM music_history WHERE guild_id=?", (guild_id,))
        for i, track in enumerate(history_data, start=1):
            await db.execute(
                "INSERT INTO music_history (guild_id, position, track_data) VALUES (?, ?, ?)",
                (guild_id, i, track),
            )
        await db.commit()


async def get_music_history(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM music_history WHERE guild_id=? ORDER BY position ASC",
            (guild_id,),
        )
        return await cursor.fetchall()


async def clear_music_state(guild_id: int) -> None:
    """Clear current track and voice channel on /stop, but keep queue and history."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE music_state SET current_track_data=NULL, current_position=0, voice_channel_id=NULL WHERE guild_id = ?",
            (guild_id,)
        )
        await db.commit()