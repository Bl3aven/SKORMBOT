"""
SKORMAgency - Music cog (Lavalink + wavelink 3.x)
Play music from SoundCloud, YouTube, Spotify, and 100+ sources via Lavalink.

Commands:
  /play <url>       - Play a track or search, optionally from a start time
  /stop             - Stop playback and clear queue
  /skip             - Skip current track
  /pause            - Pause/resume playback
  /queue            - Show current queue
  /volume <0-500>   - Set volume
  /volumedefaut <0-500> - Set default volume
  /nowplaying       - Show current track
"""
from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus, urlparse

import aiosqlite
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import wavelink

from bot.config import EMBED_COLOR, FOOTER_TEXT, BRAND_NAME
from bot.cogs import db as music_db

log = logging.getLogger("skorm.music")

SOURCE_PREFIXES = (
    "ytsearch:",
    "ytmsearch:",
    "scsearch:",
    "spsearch:",
    "amsearch:",
    "dzsearch:",
    "dcsearch:",
    "rvsearch:",
    "jjsearch:",
    "getyoutubemusic:",
)
DIRECT_URL_SCHEMES = {"http", "https"}
SEARCH_RESULT_LIMIT = 5
AUTOCOMPLETE_LIMIT = 8
METADATA_TIMEOUT_SECONDS = 4
GENERIC_OEMBED_AUTHORS = {"spotify", "youtube", "soundcloud"}
HTTP_HEADERS = {"User-Agent": "SKORMBOT/1.0 (+https://discord.com)"}
DEFAULT_MUSIC_VOLUME = music_db.DEFAULT_MUSIC_VOLUME
STATE_SAVE_INTERVAL_SECONDS = 10
TIME_TOKEN_RE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)(?P<unit>heures?|hrs?|h|minutes?|mins?|min|m|secondes?|secs?|sec|s)",
    flags=re.IGNORECASE,
)


@dataclass
class QueuedTrack:
    track: wavelink.Playable
    start_ms: int | None = None


class MusicQueue:
    """Per-guild music queue wrapper with history support."""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self._queue: list[QueuedTrack] = []
        self._history: list[wavelink.Playable] = []
        self.voice_channel_id: int | None = None  # Track connected voice channel

    @property
    def is_empty(self) -> bool:
        return len(self._queue) == 0

    @property
    def length(self) -> int:
        return len(self._queue)

    @property
    def history_length(self) -> int:
        return len(self._history)

    def put(self, track: wavelink.Playable, start_ms: int | None = None) -> None:
        self._queue.append(QueuedTrack(track=track, start_ms=start_ms))

    def get(self) -> QueuedTrack | None:
        if self._queue:
            return self._queue.pop(0)
        return None

    def clear(self) -> None:
        self._queue.clear()
        self._history.clear()

    def peek(self) -> QueuedTrack | None:
        if self._queue:
            return self._queue[0]
        return None

    def push_history(self, track: wavelink.Playable) -> None:
        """Add a track to history (most recent first, max 50)."""
        self._history.insert(0, track)
        if len(self._history) > 50:
            self._history.pop()

    def get_previous(self) -> Optional[wavelink.Playable]:
        if self._history:
            return self._history.pop(0)
        return None


# Per-guild queues
_queues: dict[int, MusicQueue] = {}


def get_queue(guild_id: int) -> MusicQueue:
    if guild_id not in _queues:
        _queues[guild_id] = MusicQueue(guild_id)
    return _queues[guild_id]


def format_time_offset(ms: int) -> str:
    seconds = max(0, ms) // 1000
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def parse_start_time(value: str | None) -> int | None:
    if value is None:
        return None

    compact = re.sub(r"\s+", "", value.strip().lower().replace(",", "."))
    if not compact:
        return None

    if ":" in compact:
        parts = compact.split(":")
        if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
            raise ValueError("Format de temps invalide. Exemples : `90s`, `1m30s`, `2:15`, `1:02:03`.")

        numbers = [int(part) for part in parts]
        if any(part >= 60 for part in numbers[1:]):
            raise ValueError("Les minutes et secondes doivent être inférieures à 60.")
        if len(numbers) == 2:
            minutes, seconds = numbers
            total_seconds = minutes * 60 + seconds
        else:
            hours, minutes, seconds = numbers
            total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds * 1000

    if re.fullmatch(r"\d+(?:\.\d+)?", compact):
        return int(float(compact) * 1000)

    total_seconds = 0.0
    position = 0
    for match in TIME_TOKEN_RE.finditer(compact):
        if match.start() != position:
            raise ValueError("Format de temps invalide. Exemples : `90s`, `1m30s`, `2:15`, `1:02:03`.")

        amount = float(match.group("amount"))
        unit = match.group("unit").lower()
        if unit.startswith(("h", "heure")):
            total_seconds += amount * 3600
        elif unit.startswith(("m", "min")):
            total_seconds += amount * 60
        else:
            total_seconds += amount
        position = match.end()

    if position != len(compact):
        raise ValueError("Format de temps invalide. Exemples : `90s`, `1m30s`, `2:15`, `1:02:03`.")

    return int(total_seconds * 1000)


def start_position_error(track: wavelink.Playable, start_ms: int | None) -> str | None:
    if not start_ms:
        return None
    if getattr(track, "is_stream", False):
        return "Impossible de démarrer à un temps précis sur un live/stream."

    length = getattr(track, "length", 0) or 0
    if length and start_ms >= length:
        return (
            f"Le départ demandé (`{format_time_offset(start_ms)}`) dépasse la durée de la piste "
            f"(`{format_duration(length)}`)."
        )
    return None


def format_track(track: wavelink.Playable, index: int = 0, start_ms: int | None = None) -> str:
    """Format a track for display."""
    duration = track.length // 1000 if track.length else 0
    minutes = duration // 60
    seconds = duration % 60
    prefix = f"{index}. " if index else ""
    lines = [
        f"**{prefix}[{track.title}]({track.uri})** — {track.author}\n"
        f"   ⏱ {minutes}:{seconds:02d}"
    ]
    if start_ms:
        lines.append(f"   ⏩ Départ : {format_time_offset(start_ms)}")
    return "\n".join(lines)


def create_embed(title: str = None, description: str = None, color: int = EMBED_COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def is_direct_url(query: str) -> bool:
    parsed = urlparse(query)
    return parsed.scheme.lower() in DIRECT_URL_SCHEMES and bool(parsed.netloc)


def is_source_prefixed(query: str) -> bool:
    query_lower = query.lower()
    return any(query_lower.startswith(prefix) for prefix in SOURCE_PREFIXES)


def split_source_prefixed(query: str) -> tuple[str, str] | None:
    query_lower = query.lower()
    for prefix in SOURCE_PREFIXES:
        if query_lower.startswith(prefix):
            return prefix, query[len(prefix):].strip()
    return None


def is_direct_query(query: str) -> bool:
    return is_direct_url(query) or is_source_prefixed(query)


def truncate_text(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def format_duration(ms: int | None) -> str:
    if not ms:
        return "live"
    seconds = ms // 1000
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def track_source(track: wavelink.Playable) -> str:
    uri = getattr(track, "uri", "") or ""
    host = urlparse(uri).netloc.lower().removeprefix("www.")
    if host:
        return host
    source = getattr(track, "source", None)
    return str(source) if source else "source inconnue"


def build_metadata_query(url: str, metadata: dict[str, object]) -> str | None:
    title = str(metadata.get("title") or "").strip()
    author = str(metadata.get("artist_name") or metadata.get("author_name") or "").strip()
    host = urlparse(url).netloc.lower()

    if not title:
        return None

    if author.lower() in GENERIC_OEMBED_AUTHORS or author.lower() in host:
        author = ""

    if author and author.lower() not in title.lower():
        return f"{author} {title}".strip()
    return title


def extract_meta_content(page_html: str, name: str) -> str:
    patterns = [
        rf"<meta\s+property=[\"']{re.escape(name)}[\"']\s+content=[\"']([^\"']+)[\"']",
        rf"<meta\s+content=[\"']([^\"']+)[\"']\s+property=[\"']{re.escape(name)}[\"']",
        rf"<meta\s+name=[\"']{re.escape(name)}[\"']\s+content=[\"']([^\"']+)[\"']",
        rf"<meta\s+content=[\"']([^\"']+)[\"']\s+name=[\"']{re.escape(name)}[\"']",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def extract_spotify_public_metadata(page_html: str) -> dict[str, object]:
    title = extract_meta_content(page_html, "og:title")
    description = extract_meta_content(page_html, "og:description")
    artist = ""

    if description:
        parts = [part.strip() for part in re.split(r"\\s+[·•]\\s+", description) if part.strip()]
        if len(parts) >= 2 and title:
            if parts[0].lower() != title.lower() and parts[1].lower() == title.lower():
                artist = parts[0]
        elif len(parts) >= 1 and title and parts[0].lower() != title.lower():
            artist = parts[0]

    if not artist:
        page_title_match = re.search(r"<title>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL)
        if page_title_match:
            page_title = html.unescape(page_title_match.group(1)).strip()
            match = re.search(r"^(.*?)\\s+-\\s+song and lyrics by\\s+(.*?)\\s+\\|\\s+Spotify$", page_title, flags=re.IGNORECASE)
            if match:
                title = title or match.group(1).strip()
                artist = match.group(2).strip()

    return {"title": title, "artist_name": artist, "description": description}


def coerce_tracks(results: object, limit: int | None = None) -> list[wavelink.Playable]:
    if not results:
        return []

    tracks = getattr(results, "tracks", None)
    if tracks is not None:
        items = list(tracks)
    elif isinstance(results, Sequence) and not isinstance(results, (str, bytes)):
        items = list(results)
    else:
        items = [results]

    usable_tracks = [
        track for track in items
        if hasattr(track, "title") and hasattr(track, "uri")
    ]
    return usable_tracks[:limit] if limit else usable_tracks


class SearchResultsView(discord.ui.View):
    """Short-lived result picker for text searches."""

    def __init__(
        self,
        cog: "MusicCog",
        requester_id: int,
        voice_channel_id: int,
        tracks: list[wavelink.Playable],
        query: str,
        start_ms: int | None = None,
    ) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.requester_id = requester_id
        self.voice_channel_id = voice_channel_id
        self.tracks = tracks[:SEARCH_RESULT_LIMIT]
        self.query = query
        self.start_ms = start_ms
        self.message: discord.Message | discord.WebhookMessage | None = None
        self.add_item(SearchResultSelect(self.tracks))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.cog._safe_message_edit(self.message, view=self)


class SearchResultSelect(discord.ui.Select):
    def __init__(self, tracks: list[wavelink.Playable]) -> None:
        options = []
        for index, track in enumerate(tracks):
            title = truncate_text(getattr(track, "title", "") or "Sans titre", 100)
            description = truncate_text(
                f"{getattr(track, 'author', 'Inconnu')} • "
                f"{format_duration(getattr(track, 'length', 0))} • {track_source(track)}",
                100,
            )
            options.append(
                discord.SelectOption(
                    label=title,
                    value=str(index),
                    description=description,
                )
            )

        super().__init__(
            placeholder="Choisis la piste à lancer",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, SearchResultsView):
            await interaction.response.send_message("❌ Sélection invalide.", ephemeral=True)
            return

        if interaction.user.id != view.requester_id:
            await interaction.response.send_message(
                "❌ Seule la personne qui a lancé la recherche peut choisir ce résultat.",
                ephemeral=True,
            )
            return

        try:
            index = int(self.values[0])
            track = view.tracks[index]
        except (ValueError, IndexError):
            await interaction.response.send_message("❌ Résultat introuvable.", ephemeral=True)
            return

        await interaction.response.defer()
        await view.cog._enqueue_or_play_track(
            interaction=interaction,
            track=track,
            voice_channel_id=view.voice_channel_id,
            start_ms=view.start_ms,
        )

        for child in view.children:
            child.disabled = True
        message = view.message or interaction.message
        if message:
            await view.cog._safe_message_edit(message, view=view)
        view.stop()


class MusicCog(commands.Cog):
    """Music playback via Lavalink."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._save_task = None
        self._spotify_oauth_available: bool | None = None

    async def cog_unload(self) -> None:
        if self._save_task:
            self._save_task.cancel()
        await self._save_all_states()
        _queues.clear()

    async def cog_load(self) -> None:
        """Start periodic state save task."""
        self._save_task = asyncio.create_task(self._periodic_save())

    async def _periodic_save(self) -> None:
        """Save music state periodically so playback can resume after a restart."""
        try:
            while True:
                await asyncio.sleep(STATE_SAVE_INTERVAL_SECONDS)
                await self._save_all_states()
        except asyncio.CancelledError:
            return

    async def _save_all_states(self) -> None:
        """Save music state for all guilds."""
        guild_ids = set(_queues)
        for guild in self.bot.guilds:
            if self._get_player_by_id(guild.id):
                guild_ids.add(guild.id)

        for guild_id in guild_ids:
            queue = get_queue(guild_id)
            player = self._get_player_by_id(guild_id)
            if (
                player is None
                and queue.is_empty
                and not queue._history
                and queue.voice_channel_id is None
            ):
                continue
            await self._save_state(guild_id)

    async def _save_state(self, guild_id: int) -> None:
        """Save current music state to database."""
        queue = get_queue(guild_id)
        player = self._get_player_by_id(guild_id)

        # Serialize current track
        current_track_data = None
        position = 0
        is_paused = False
        volume = DEFAULT_MUSIC_VOLUME
        voice_channel_id = queue.voice_channel_id

        if player:
            voice_channel = getattr(player, "channel", None)
            if getattr(voice_channel, "id", None):
                voice_channel_id = voice_channel.id
            if player.current:
                current_track_data = self._serialize_track(player.current)
                position = int(getattr(player, "position", 0) or 0)
                is_paused = player.paused
                volume = int(getattr(player, "volume", DEFAULT_MUSIC_VOLUME) or DEFAULT_MUSIC_VOLUME)

        # Serialize queue
        queue_data = [self._serialize_queue_item(item) for item in queue._queue]
        history_data = [self._serialize_track(t) for t in queue._history]

        await music_db.save_music_state(guild_id, current_track_data, position, is_paused, volume, voice_channel_id)
        await music_db.save_music_queue(guild_id, queue_data)
        await music_db.save_music_history(guild_id, history_data)

    async def _clear_saved_playback(self, guild_id: int, clear_history: bool = False) -> None:
        await music_db.clear_music_state(guild_id)
        await music_db.save_music_queue(guild_id, [])
        if clear_history:
            await music_db.save_music_history(guild_id, [])

    @staticmethod
    def _serialize_track(track: wavelink.Playable) -> str:
        """Serialize a track to JSON string."""
        return json.dumps(MusicCog._serialize_track_payload(track))

    @staticmethod
    def _serialize_track_payload(track: wavelink.Playable) -> dict[str, object]:
        return {
            "identifier": track.identifier,
            "title": track.title,
            "author": track.author,
            "uri": track.uri,
            "length": track.length,
            "is_stream": track.is_stream,
        }

    @staticmethod
    def _serialize_queue_item(item: QueuedTrack) -> str:
        """Serialize a queued track with its optional start offset."""
        payload = MusicCog._serialize_track_payload(item.track)
        payload["start_ms"] = item.start_ms
        return json.dumps(payload)

    @staticmethod
    def _deserialize_track(data: str) -> dict:
        """Deserialize track data from JSON string."""
        return json.loads(data)

    async def _load_track_from_data(self, track_data: dict[str, object]) -> wavelink.Playable | None:
        """Reload a serialized track through Lavalink."""
        identifiers = [
            str(track_data.get("uri") or "").strip(),
            str(track_data.get("identifier") or "").strip(),
        ]
        for identifier in identifiers:
            if not identifier:
                continue
            try:
                tracks = await self._fetch_tracks(identifier)
            except Exception as exc:
                log.warning("Failed to reload saved track %s: %s", identifier[:100], exc)
                continue
            if tracks:
                return tracks[0]
        return None

    @staticmethod
    def _saved_start_ms(track_data: dict[str, object]) -> int | None:
        value = track_data.get("start_ms")
        if value is None:
            return None
        try:
            start_ms = int(value)
        except (TypeError, ValueError):
            return None
        return start_ms if start_ms > 0 else None

    @staticmethod
    def _saved_position_ms(state: aiosqlite.Row) -> int:
        try:
            return max(0, int(state["current_position"] or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _saved_volume(state: aiosqlite.Row) -> int:
        try:
            return max(0, min(500, int(state["volume"] or DEFAULT_MUSIC_VOLUME)))
        except (TypeError, ValueError):
            return DEFAULT_MUSIC_VOLUME

    async def _restore_queue_items(self, guild_id: int, queue: MusicQueue) -> int:
        restored = 0
        queue._queue.clear()
        queue_rows = await music_db.get_music_queue(guild_id)
        for row in queue_rows:
            try:
                track_data = self._deserialize_track(row["track_data"])
            except Exception as exc:
                log.warning("Failed to decode saved queue item for guild %s: %s", guild_id, exc)
                continue

            track = await self._load_track_from_data(track_data)
            if track is None:
                continue
            queue.put(track, start_ms=self._saved_start_ms(track_data))
            restored += 1
        return restored

    async def _restore_history_items(self, guild_id: int, queue: MusicQueue) -> int:
        restored = 0
        queue._history.clear()
        history_rows = await music_db.get_music_history(guild_id)
        for row in history_rows:
            try:
                track_data = self._deserialize_track(row["track_data"])
            except Exception as exc:
                log.warning("Failed to decode saved history item for guild %s: %s", guild_id, exc)
                continue

            track = await self._load_track_from_data(track_data)
            if track is None:
                continue
            queue._history.append(track)
            restored += 1
        return restored

    def _get_player_by_id(self, guild_id: int) -> wavelink.Player | None:
        """Get player by guild ID without needing Guild object."""
        pool = getattr(self.bot, "wavelink", None)
        if pool is None:
            return None
        try:
            node = pool.get_node()
            return node.get_player(guild_id)
        except Exception:
            return None

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Restore music state on bot startup after Lavalink is connected."""
        # Wait for bot.wavelink to be set (by _connect_lavalink in main.py)
        for attempt in range(60):  # Max 60 seconds
            await asyncio.sleep(1)
            if getattr(self.bot, 'wavelink', None) is not None:
                log.info("Lavalink connected, restoring music state...")
                await self._restore_all_states()
                return
        log.warning("Lavalink not connected after 60s, skipping music restore")

    async def _restore_all_states(self) -> None:
        """Restore music state for all guilds from database."""
        try:
            # Get all guilds with saved state
            async with aiosqlite.connect(music_db.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("SELECT * FROM music_state")
                states = await cursor.fetchall()

            for state in states:
                guild_id = state["guild_id"]
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    continue

                queue = get_queue(guild_id)

                restored_queue = await self._restore_queue_items(guild_id, queue)
                restored_history = await self._restore_history_items(guild_id, queue)
                if restored_queue or restored_history:
                    log.info(
                        "Restored saved music queue for guild %s: %d queued, %d history",
                        guild_id,
                        restored_queue,
                        restored_history,
                    )

                # Restore current track if exists
                if state["current_track_data"]:
                    try:
                        current_data = self._deserialize_track(state["current_track_data"])
                    except Exception as exc:
                        log.warning("Failed to decode saved current track for guild %s: %s", guild_id, exc)
                        continue
                    log.info("Restoring music state for guild %s: %s", guild_id, current_data.get("title"))

                    # Connect to voice channel if it exists
                    voice_channel = guild.get_channel(state["voice_channel_id"])
                    if isinstance(voice_channel, discord.VoiceChannel):
                        try:
                            player = await self._ensure_player(guild, voice_channel)
                            track = await self._load_track_from_data(current_data)
                            if track is None:
                                log.warning("Saved current track could not be reloaded for guild %s", guild_id)
                                continue

                            resume_position = self._saved_position_ms(state)
                            if track.length and resume_position >= track.length:
                                resume_position = max(0, track.length - 1000)

                            saved_volume = self._saved_volume(state)
                            if saved_volume != getattr(player, "volume", DEFAULT_MUSIC_VOLUME):
                                await player.set_volume(saved_volume)

                            await self._play_track(
                                player,
                                track,
                                guild,
                                voice_channel,
                                start_ms=resume_position,
                            )
                            if state["is_paused"]:
                                await player.pause(True)
                            log.info(
                                "Restored playback: %s at %s (%d queued)",
                                track.title,
                                format_time_offset(resume_position),
                                queue.length,
                            )
                        except Exception as exc:
                            log.error("Failed to restore playback for guild %s: %s", guild_id, exc)
                    else:
                        log.warning("Saved voice channel %s not found for guild %s", state["voice_channel_id"], guild_id)

        except Exception as exc:
            log.error("Failed to restore music states: %s", exc)

    # --- Wavelink 3.x events (dispatched as on_wavelink_*) ---

    @commands.Cog.listener("on_wavelink_track_end")
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        """Play next track from queue when current track ends."""
        player = payload.player
        guild_id = player.guild.id
        queue = get_queue(guild_id)

        log.info("Track ended in guild %s, queue size: %d, player playing: %s", guild_id, queue.length, player.playing)

        # If player is already playing, a new track was started (e.g. by /next) — don't stop
        if player.playing:
            log.info("Player already playing new track, skipping queue handling")
            return

        ended_track = getattr(payload, "track", None)
        if ended_track:
            queue.push_history(ended_track)

        if queue.is_empty:
            log.info("Queue empty, stopping player in guild %s", guild_id)
            await player.stop()
            await self._clear_saved_playback(guild_id)
            return

        next_item = queue.get()
        if next_item:
            next_track = next_item.track
            log.info("Auto-playing next track from queue: %s", next_track.title)
            try:
                voice_channel = getattr(player, "channel", None)
                if isinstance(voice_channel, discord.VoiceChannel):
                    await self._play_track(
                        player,
                        next_track,
                        player.guild,
                        voice_channel,
                        start_ms=next_item.start_ms,
                    )
                else:
                    await player.play(next_track)
                    await self._seek_to_start(player, next_track, next_item.start_ms)
            except Exception as exc:
                log.error("Failed to auto-play next track: %s", exc, exc_info=True)
                queue._queue.insert(0, next_item)
            else:
                await self._save_state(guild_id)

    @commands.Cog.listener("on_wavelink_track_stuck")
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload) -> None:
        log.warning("Track stuck: %s", payload.track.title)

    @commands.Cog.listener("on_wavelink_track_exception")
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload) -> None:
        log.error("Lavalink track exception: %s", payload.exception)

    # --- Helper to get player ---

    def _get_player(self, guild: discord.Guild) -> wavelink.Player | None:
        pool = getattr(self.bot, "wavelink", None)
        if pool is None:
            return None
        try:
            node = pool.get_node()
            return node.get_player(guild.id)
        except Exception as exc:
            log.debug("Unable to get Lavalink player for guild %s: %s", guild.id, exc)
            return None

    @staticmethod
    def _clamp_volume(level: int) -> int:
        return max(0, min(500, int(level)))

    async def _get_default_volume(self, guild_id: int) -> int:
        try:
            return self._clamp_volume(await music_db.get_default_volume(guild_id))
        except Exception as exc:
            log.warning("Failed to load default music volume for guild %s: %s", guild_id, exc)
            return DEFAULT_MUSIC_VOLUME

    async def _apply_default_volume(self, guild: discord.Guild, player: wavelink.Player) -> None:
        volume = await self._get_default_volume(guild.id)
        if getattr(player, "volume", None) == volume:
            return
        try:
            await player.set_volume(volume)
        except Exception as exc:
            log.warning("Failed to apply default music volume for guild %s: %s", guild.id, exc)

    async def _ensure_player(self, guild: discord.Guild, voice_channel: discord.VoiceChannel) -> wavelink.Player:
        """Get existing player or connect to voice channel."""
        player = self._get_player(guild)
        if player and player.connected:
            get_queue(guild.id).voice_channel_id = voice_channel.id
            if not player.playing and player.current is None:
                await self._apply_default_volume(guild, player)
            return player

        # Connect to voice channel - wavelink 3.x creates player automatically
        await voice_channel.connect(cls=wavelink.Player)
        # After connect, get the player from node
        player = self._get_player(guild)
        if player is None:
            raise RuntimeError("Player not created after voice connect")
        
        # Save voice channel ID to queue for persistence
        queue = get_queue(guild.id)
        queue.voice_channel_id = voice_channel.id
        await self._apply_default_volume(guild, player)
        
        return player

    async def _safe_message_edit(self, message: object, **kwargs) -> None:
        try:
            await message.edit(**kwargs)
        except discord.NotFound:
            log.info("Skipped edit for a deleted Discord message")
        except discord.HTTPException as exc:
            log.warning("Failed to edit Discord message: %s", exc)

    async def _send_interaction_message(
        self,
        interaction: discord.Interaction,
        content: str | None = None,
        **kwargs,
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content, **kwargs)
        else:
            await interaction.response.send_message(content, **kwargs)

    @staticmethod
    def _is_lavalink_session_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "404" in message
            or "not found" in message
            or "session" in message and "invalid" in message
            or "no player" in message
        )

    @staticmethod
    def _search_error_message(query: str, exc: Exception) -> str:
        message = str(exc)
        lower_message = message.lower()
        if "spotify" in query.lower() or "invalid_client" in lower_message:
            return (
                "❌ Spotify n'est pas encore utilisable : les credentials LavaSrc sont invalides. "
                "Ajoute une app Spotify dédiée avec `SPOTIFY_CLIENT_ID` et "
                "`SPOTIFY_CLIENT_SECRET`, puis relance Lavalink."
            )
        if (
            "failed to load tracks" in lower_message
            or "looking up the track" in lower_message
            or "friendlyexception" in lower_message
        ):
            return (
                "❌ Lavalink n'a pas réussi à charger cette piste. "
                "J'ai essayé les fallbacks disponibles ; essaie une URL YouTube/SoundCloud "
                "ou une recherche plus précise avec artiste + titre."
            )
        return f"❌ Erreur lors de la recherche : {message}"

    async def _reset_stale_player(self, guild: discord.Guild) -> None:
        voice_client = guild.voice_client
        if voice_client is None:
            return

        try:
            await voice_client.disconnect(force=True)
        except TypeError:
            try:
                await voice_client.disconnect()
            except Exception as exc:
                log.debug("Failed to disconnect stale voice client: %s", exc)
        except Exception as exc:
            log.debug("Failed to disconnect stale voice client: %s", exc)

    async def _play_track(
        self,
        player: wavelink.Player,
        track: wavelink.Playable,
        guild: discord.Guild,
        voice_channel: discord.VoiceChannel,
        start_ms: int | None = None,
    ) -> wavelink.Player:
        try:
            await player.play(track)
            await self._seek_to_start(player, track, start_ms)
            return player
        except Exception as exc:
            if not self._is_lavalink_session_error(exc):
                raise

            log.warning("Lavalink player session was stale, reconnecting: %s", exc)
            await self._reset_stale_player(guild)
            player = await self._ensure_player(guild, voice_channel)
            await player.play(track)
            await self._seek_to_start(player, track, start_ms)
            return player

    async def _seek_to_start(
        self,
        player: wavelink.Player,
        track: wavelink.Playable,
        start_ms: int | None,
    ) -> None:
        error = start_position_error(track, start_ms)
        if error:
            raise ValueError(error)
        if start_ms:
            await player.seek(start_ms)

    async def _fetch_tracks(self, query: str, limit: int | None = None) -> list[wavelink.Playable]:
        pool = getattr(self.bot, "wavelink", None)
        if pool is None:
            raise RuntimeError("Lavalink n'est pas connecté")

        results = await pool.fetch_tracks(query)
        return coerce_tracks(results, limit=limit)

    async def _spotify_oauth_is_available(self) -> bool:
        if self._spotify_oauth_available is not None:
            return self._spotify_oauth_available

        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            self._spotify_oauth_available = False
            log.warning("Spotify OAuth unavailable: missing SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET")
            return False

        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        timeout = aiohttp.ClientTimeout(total=METADATA_TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=HTTP_HEADERS) as session:
                async with session.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"},
                    headers={
                        "Authorization": f"Basic {auth}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                ) as response:
                    payload = await response.text()
                    self._spotify_oauth_available = response.status == 200 and "access_token" in payload
        except Exception as exc:
            log.warning("Spotify OAuth check failed: %s", exc)
            self._spotify_oauth_available = False

        if not self._spotify_oauth_available:
            log.warning("Spotify OAuth unavailable: LavaSrc Spotify direct lookup will be bypassed")
        return self._spotify_oauth_available

    @staticmethod
    def _search_strategies(query: str) -> list[str]:
        query = query.strip()
        if not query:
            return []
        return [
            f"ytsearch:{query}",
            f"scsearch:{query}",
            query,
        ]

    @staticmethod
    def _fallback_strategies_for_prefixed_query(query: str) -> list[str]:
        parts = split_source_prefixed(query)
        if not parts:
            return [query]

        _, search_term = parts
        strategies = [query]
        if not search_term:
            return strategies

        for strategy in MusicCog._search_strategies(search_term):
            if strategy.lower() != query.lower() and strategy not in strategies:
                strategies.append(strategy)
        return strategies

    async def _fetch_url_metadata_query(self, url: str) -> str | None:
        host = urlparse(url).netloc.lower()
        encoded_url = quote_plus(url)

        endpoints = []
        if "open.spotify.com" in host:
            endpoints.append(f"https://open.spotify.com/oembed?url={encoded_url}")
        if "youtube.com" in host or "youtu.be" in host:
            endpoints.append(f"https://www.youtube.com/oembed?format=json&url={encoded_url}")
        if "soundcloud.com" in host:
            endpoints.append(f"https://soundcloud.com/oembed?format=json&url={encoded_url}")
        endpoints.append(f"https://noembed.com/embed?url={encoded_url}")

        timeout = aiohttp.ClientTimeout(total=METADATA_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout, headers=HTTP_HEADERS) as session:
            if "open.spotify.com" in host:
                try:
                    async with session.get(url) as response:
                        if response.status < 400:
                            page_html = await response.text()
                            metadata_query = build_metadata_query(
                                url,
                                extract_spotify_public_metadata(page_html),
                            )
                            if metadata_query:
                                return metadata_query
                except Exception as exc:
                    log.debug("Spotify public metadata lookup failed for %s: %s", url, exc)

            for endpoint in endpoints:
                try:
                    async with session.get(endpoint) as response:
                        if response.status >= 400:
                            continue
                        payload = await response.json(content_type=None)
                except Exception as exc:
                    log.debug("oEmbed lookup failed for %s: %s", endpoint, exc)
                    continue

                metadata_query = build_metadata_query(url, payload)
                if metadata_query:
                    return metadata_query

        return None

    async def _resolve_tracks(self, query: str) -> tuple[list[wavelink.Playable], str]:
        last_error: Exception | None = None

        if is_direct_url(query):
            host = urlparse(query).netloc.lower()
            spotify_url = "open.spotify.com" in host
            if not spotify_url or await self._spotify_oauth_is_available():
                try:
                    tracks = await self._fetch_tracks(query)
                except Exception as exc:
                    last_error = exc
                    log.warning("Direct URL lookup failed (%s): %s", query[:100], exc)
                else:
                    if tracks:
                        return tracks, query
            else:
                log.info("Skipping direct Spotify Lavalink lookup because OAuth is unavailable")

            metadata_query = await self._fetch_url_metadata_query(query)
            if metadata_query:
                log.info("Retrying URL as metadata search: %s", metadata_query[:100])
                strategies = self._search_strategies(metadata_query)
            else:
                strategies = []
        elif is_source_prefixed(query):
            strategies = self._fallback_strategies_for_prefixed_query(query)
        else:
            strategies = self._search_strategies(query)

        for strategy in strategies:
            try:
                tracks = await self._fetch_tracks(strategy)
            except Exception as exc:
                last_error = exc
                log.warning("Music search strategy failed (%s): %s", strategy[:100], exc)
                continue

            if tracks:
                return tracks, strategy

        if last_error:
            raise last_error
        return [], strategies[0] if strategies else query

    async def _enqueue_or_play_track(
        self,
        interaction: discord.Interaction,
        track: wavelink.Playable,
        voice_channel_id: int,
        start_ms: int | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await self._send_interaction_message(
                interaction,
                "❌ Cette commande ne fonctionne que dans un serveur.",
                ephemeral=True,
            )
            return

        voice_channel = guild.get_channel(voice_channel_id)
        if not isinstance(voice_channel, discord.VoiceChannel):
            user_voice = getattr(interaction.user, "voice", None)
            voice_channel = user_voice.channel if user_voice else None

        if not isinstance(voice_channel, discord.VoiceChannel):
            await self._send_interaction_message(
                interaction,
                "❌ Rejoins un salon vocal valide avant de lancer la lecture.",
                ephemeral=True,
            )
            return

        error = start_position_error(track, start_ms)
        if error:
            await self._send_interaction_message(interaction, f"❌ {error}", ephemeral=True)
            return

        try:
            player = await self._ensure_player(guild, voice_channel)
        except Exception as exc:
            await self._send_interaction_message(
                interaction,
                f"❌ Impossible de rejoindre le salon vocal : {exc}",
            )
            return

        queue = get_queue(guild.id)
        try:
            if player.playing:
                queue.put(track, start_ms=start_ms)
                await self._send_interaction_message(
                    interaction,
                    f"✅ Ajouté à la file :\n{format_track(track, queue.length, start_ms=start_ms)}",
                )
            else:
                await self._play_track(player, track, guild, voice_channel, start_ms=start_ms)
                await self._send_interaction_message(
                    interaction,
                    f"🎵 En lecture :\n{format_track(track, start_ms=start_ms)}",
                )

            await self._save_state(guild.id)
        except Exception as exc:
            log.error("Failed to play selected track: %s", exc, exc_info=True)
            if self._is_lavalink_session_error(exc):
                await self._send_interaction_message(
                    interaction,
                    "❌ La session Lavalink a expiré. Relance `/play` pour recréer le player.",
                    ephemeral=True,
                )
            else:
                await self._send_interaction_message(
                    interaction,
                    f"❌ Impossible de lancer la piste : {exc}",
                    ephemeral=True,
                )

    async def _handle_player_error(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        exc: Exception,
    ) -> None:
        log.error("Lavalink player operation failed: %s", exc, exc_info=True)
        if self._is_lavalink_session_error(exc):
            await self._reset_stale_player(guild)
            await self._send_interaction_message(
                interaction,
                "❌ La session Lavalink a expiré. Relance `/play` pour recréer le player.",
                ephemeral=True,
            )
            return

        await self._send_interaction_message(
            interaction,
            f"❌ Erreur Lavalink : {exc}",
            ephemeral=True,
        )

    async def _send_search_picker(
        self,
        interaction: discord.Interaction,
        query: str,
        voice_channel: discord.VoiceChannel,
        tracks: list[wavelink.Playable],
        start_ms: int | None = None,
    ) -> None:
        lines = []
        for index, track in enumerate(tracks[:SEARCH_RESULT_LIMIT], start=1):
            lines.append(
                f"**{index}. [{truncate_text(track.title, 80)}]({track.uri})** — "
                f"{truncate_text(track.author, 50)} "
                f"`{format_duration(track.length)}`"
            )

        embed = create_embed(
            title="Résultats de recherche",
            description="\n".join(lines),
        )
        embed.add_field(
            name="Recherche",
            value=f"`{truncate_text(query, 200)}`",
            inline=False,
        )
        if start_ms:
            embed.add_field(
                name="Départ",
                value=f"`{format_time_offset(start_ms)}`",
                inline=False,
            )

        view = SearchResultsView(
            cog=self,
            requester_id=interaction.user.id,
            voice_channel_id=voice_channel.id,
            tracks=tracks,
            query=query,
            start_ms=start_ms,
        )
        message = await interaction.followup.send(embed=embed, view=view, wait=True)
        view.message = message

    # --- Slash commands ---

    @app_commands.command(name="play", description="Joue une musique (SoundCloud, YouTube, Spotify, etc.)")
    @app_commands.describe(
        query="URL, recherche texte, suggestion, ou numéro de la file d'attente",
        debut="Temps de départ optionnel : 90s, 1m30s, 2:15, 1:02:03",
    )
    async def play(self, interaction: discord.Interaction, query: str, debut: str | None = None) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ Cette commande ne fonctionne que dans un serveur.", ephemeral=True)
            return

        # Check voice connection
        voice_channel = interaction.user.voice.channel if interaction.user.voice else None
        if not voice_channel:
            await interaction.response.send_message("❌ Rejoins d'abord un salon vocal !", ephemeral=True)
            return

        try:
            requested_start_ms = parse_start_time(debut)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return

        await interaction.response.defer()

        # Check if query is a number (play from queue by index)
        query_str = query.strip()
        if not query_str:
            await interaction.followup.send("❌ Indique une URL ou une recherche.")
            return

        queue = get_queue(guild.id)

        if query_str.isdigit():
            try:
                player = await self._ensure_player(guild, voice_channel)
            except Exception as exc:
                await interaction.followup.send(f"❌ Impossible de rejoindre le salon vocal : {exc}")
                return

            index = int(query_str)
            if index < 1 or index > queue.length:
                await interaction.followup.send(f"❌ Index invalide. La file contient {queue.length} piste(s). Utilise `/queue` pour voir la liste.")
                return

            # Get track at index (1-based)
            queued_item = queue._queue.pop(index - 1)
            track = queued_item.track
            start_ms = requested_start_ms if requested_start_ms is not None else queued_item.start_ms
            log.info("Playing track #%d from queue: %s", index, track.title)

            error = start_position_error(track, start_ms)
            if error:
                queue._queue.insert(index - 1, queued_item)
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            if player.playing:
                # Save current track to history
                if player.current:
                    queue.push_history(player.current)
            try:
                await self._play_track(player, track, guild, voice_channel, start_ms=start_ms)
            except Exception as exc:
                log.error("Failed to play queued track #%d: %s", index, exc, exc_info=True)
                queue._queue.insert(index - 1, queued_item)
                await interaction.followup.send(f"❌ Impossible de lancer la piste #{index} : {exc}")
                return

            await interaction.followup.send(
                f"🎵 Lecture de la piste #{index} :\n{format_track(track, start_ms=start_ms)}"
            )
            await self._save_state(guild.id)
            return

        # Search for track
        log.info("Music search query: %s", query_str[:100])

        try:
            tracks, resolved_query = await self._resolve_tracks(query_str)
        except Exception as search_exc:
            log.error("Lavalink search failed for '%s': %s", query_str[:100], search_exc, exc_info=True)
            await interaction.followup.send(self._search_error_message(query_str, search_exc))
            return

        log.info("Search returned %d result(s) for: %s", len(tracks), resolved_query[:100])
        
        if not tracks:
            log.warning("No tracks found for query: %s", query_str[:100])
            await interaction.followup.send(
                "❌ Aucun résultat trouvé. Vérifie l'URL ou essaie une recherche plus précise "
                "(artiste + titre)."
            )
            return

        if is_direct_query(query_str) or len(tracks) == 1:
            await self._enqueue_or_play_track(
                interaction,
                tracks[0],
                voice_channel.id,
                start_ms=requested_start_ms,
            )
            return

        await self._send_search_picker(
            interaction,
            query_str,
            voice_channel,
            tracks,
            start_ms=requested_start_ms,
        )

    @play.autocomplete("query")
    async def play_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        query = current.strip()
        if len(query) < 3 or query.isdigit() or is_direct_url(query):
            return []

        tracks = []
        for strategy in self._search_strategies(query)[:2]:
            try:
                tracks = await self._fetch_tracks(strategy, limit=AUTOCOMPLETE_LIMIT)
            except Exception as exc:
                log.debug("Music autocomplete strategy failed (%s): %s", strategy[:80], exc)
                continue
            if tracks:
                break

        if not tracks:
            return []

        choices: list[app_commands.Choice[str]] = []
        for track in tracks:
            label = truncate_text(
                f"{track.title} — {track.author} ({format_duration(track.length)})",
                100,
            )
            value = truncate_text(f"ytsearch:{track.title} {track.author}", 100)
            choices.append(app_commands.Choice(name=label, value=value))
        return choices

    @app_commands.command(name="stop", description="Arrête la musique et vide la file d'attente")
    async def stop(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self._get_player(guild)

        if player is None or not player.connected:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        get_queue(guild.id).clear()
        try:
            await player.stop()
            await player.disconnect()
        except Exception as exc:
            await self._handle_player_error(interaction, guild, exc)
            return
        get_queue(guild.id).voice_channel_id = None
        await self._clear_saved_playback(guild.id, clear_history=True)
        await interaction.response.send_message("🛑 Musique arrêtée et file d'attente vidée.")

    @app_commands.command(name="skip", description="Passe à la piste suivante")
    async def skip(self, interaction: discord.Interaction) -> None:
        await self._handle_next(interaction)

    @app_commands.command(name="next", description="Passe à la musique suivante")
    async def next_track(self, interaction: discord.Interaction) -> None:
        await self._handle_next(interaction)

    @app_commands.command(name="previous", description="Rejoue la musique précédente")
    async def previous_track(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ Cette commande ne fonctionne que dans un serveur.", ephemeral=True)
            return

        player = self._get_player(guild)

        if player is None or not player.connected:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        queue = get_queue(guild.id)

        if queue.history_length == 0:
            await interaction.response.send_message("⏮ Aucune musique précédente.", ephemeral=True)
            return

        prev_track = queue.get_previous()
        if prev_track:
            log.info("Playing previous track: %s", prev_track.title)
            current_track = player.current
            if current_track:
                queue.push_history(current_track)
            voice_channel = getattr(player, "channel", None)
            if not isinstance(voice_channel, discord.VoiceChannel):
                user_voice = getattr(interaction.user, "voice", None)
                voice_channel = user_voice.channel if user_voice else None
            if not isinstance(voice_channel, discord.VoiceChannel):
                queue.push_history(prev_track)
                await interaction.response.send_message("❌ Salon vocal introuvable.", ephemeral=True)
                return
            try:
                await self._play_track(player, prev_track, guild, voice_channel)
            except Exception as exc:
                queue.push_history(prev_track)
                await self._handle_player_error(interaction, guild, exc)
                return
            await self._save_state(guild.id)
            await interaction.response.send_message(f"⏮ Lecture précédente :\n{format_track(prev_track)}")
        else:
            await interaction.response.send_message("⏮ Aucune musique précédente.", ephemeral=True)

    async def _handle_next(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ Cette commande ne fonctionne que dans un serveur.", ephemeral=True)
            return

        player = self._get_player(guild)

        if player is None or not player.playing:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        queue = get_queue(guild.id)

        # Save current track to history before skipping
        if player.current:
            queue.push_history(player.current)

        if queue.is_empty:
            # No queued tracks — just skip current
            try:
                await player.skip()
            except Exception as exc:
                await self._handle_player_error(interaction, guild, exc)
                return
            await self._save_state(guild.id)
            await interaction.response.send_message("⏭ Piste suivante (file vide).")
            return

        # Play next from queue
        next_item = queue.get()
        if next_item:
            next_track = next_item.track
            log.info("Skipping to next queued track: %s", next_track.title)
            voice_channel = getattr(player, "channel", None)
            if not isinstance(voice_channel, discord.VoiceChannel):
                user_voice = getattr(interaction.user, "voice", None)
                voice_channel = user_voice.channel if user_voice else None
            if not isinstance(voice_channel, discord.VoiceChannel):
                queue._queue.insert(0, next_item)
                await interaction.response.send_message("❌ Salon vocal introuvable.", ephemeral=True)
                return
            try:
                await self._play_track(
                    player,
                    next_track,
                    guild,
                    voice_channel,
                    start_ms=next_item.start_ms,
                )
            except Exception as exc:
                queue._queue.insert(0, next_item)
                await self._handle_player_error(interaction, guild, exc)
                return
            await self._save_state(guild.id)
            await interaction.response.send_message(
                f"⏭ Lecture suivante :\n{format_track(next_track, start_ms=next_item.start_ms)}"
            )
        else:
            try:
                await player.skip()
            except Exception as exc:
                await self._handle_player_error(interaction, guild, exc)
                return
            await self._save_state(guild.id)
            await interaction.response.send_message("⏭ Piste suivante.")

    @app_commands.command(name="pause", description="Met en pause ou reprend la lecture")
    async def pause(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self._get_player(guild)

        if player is None or not player.connected:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        try:
            if player.paused:
                await player.pause(False)
                await self._save_state(guild.id)
                await interaction.response.send_message("▶ Lecture reprise.")
            else:
                await player.pause(True)
                await self._save_state(guild.id)
                await interaction.response.send_message("⏸ Lecture en pause.")
        except Exception as exc:
            await self._handle_player_error(interaction, guild, exc)

    @app_commands.command(name="queue", description="Affiche la file d'attente")
    async def queue_cmd(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self._get_player(guild)
        queue = get_queue(guild.id)

        if player is None or (not player.playing and queue.is_empty):
            await interaction.response.send_message("🎵 File d'attente vide. Utilise `/play <url>` pour commencer !", ephemeral=True)
            return

        lines = []

        # Current track
        if player and player.current:
            current = player.current
            duration = current.length // 1000 if current.length else 0
            minutes = duration // 60
            seconds = duration % 60
            lines.append(f"**🎵 En lecture :**\n**{current.title}** — {current.author}\n   ⏱ {minutes}:{seconds:02d}")

        # Queue
        if not queue.is_empty:
            lines.append("**📋 File d'attente :**")
            for i, item in enumerate(queue._queue, start=1):
                track = item.track
                duration = track.length // 1000 if track.length else 0
                minutes = duration // 60
                seconds = duration % 60
                line = f"**{i}. [{track.title}]({track.uri})** — {track.author}\n   ⏱ {minutes}:{seconds:02d}"
                if item.start_ms:
                    line += f"\n   ⏩ Départ : {format_time_offset(item.start_ms)}"
                lines.append(line)
        else:
            lines.append("*Aucune piste en attente.*")

        description = "\n\n".join(lines)
        embed = create_embed(
            title=f"🎵 File d'attente — {BRAND_NAME}",
            description=description[:4000],
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Régle le volume de la lecture en cours (0-500)")
    @app_commands.describe(level="Volume actuel de 0 à 500")
    async def volume(self, interaction: discord.Interaction, level: int) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self._get_player(guild)

        if player is None or not player.connected:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        level = self._clamp_volume(level)
        try:
            await player.set_volume(level)
        except Exception as exc:
            await self._handle_player_error(interaction, guild, exc)
            return
        await self._save_state(guild.id)
        await interaction.response.send_message(f"🔊 Volume réglé à {level}%.")

    @app_commands.command(name="volumedefaut", description="Définit le volume par défaut des nouvelles lectures")
    @app_commands.describe(level="Volume par défaut de 0 à 500 (20 conseillé)")
    @app_commands.default_permissions(manage_guild=True)
    async def default_volume(self, interaction: discord.Interaction, level: int) -> None:
        guild = interaction.guild
        if guild is None:
            return

        level = self._clamp_volume(level)
        try:
            await music_db.save_default_volume(guild.id, level)
        except Exception as exc:
            log.error("Failed to save default music volume for guild %s: %s", guild.id, exc, exc_info=True)
            await interaction.response.send_message(
                "❌ Impossible d'enregistrer le volume par défaut.",
                ephemeral=True,
            )
            return

        player = self._get_player(guild)
        note = ""
        if player and player.connected and not player.playing and player.current is None:
            try:
                await player.set_volume(level)
                note = " Le player connecté inactif est déjà réglé sur ce volume."
            except Exception as exc:
                log.warning("Failed to apply saved default volume immediately for guild %s: %s", guild.id, exc)
        elif player and player.connected:
            note = " La lecture en cours garde son volume actuel ; utilise `/volume` pour la changer maintenant."

        await interaction.response.send_message(
            f"🔊 Volume par défaut réglé à {level}%.{note}",
            ephemeral=True,
        )

    @app_commands.command(name="nowplaying", description="Affiche la piste en cours")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self._get_player(guild)

        if player is None or player.current is None:
            await interaction.response.send_message("🎵 Aucune musique en cours de lecture.", ephemeral=True)
            return

        track = player.current

        progress = player.position
        duration = track.length

        def _progress_bar(current: int, total: int, width: int = 15) -> str:
            if total <= 0:
                return "▬" * width
            filled = int(width * current / total)
            return "▬" * filled + "▬" * (width - filled)

        def _fmt(ms: int) -> str:
            s = ms // 1000
            m, s = divmod(s, 60)
            return f"{m}:{s:02d}"

        bar = _progress_bar(progress, duration)
        embed = create_embed(
            title=f"🎵 En lecture",
            description=(
                f"[**{track.title}**]({track.uri}) — {track.author}\n\n"
                f"{bar} `{_fmt(progress)}` / `{_fmt(duration)}`"
            ),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
