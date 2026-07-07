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