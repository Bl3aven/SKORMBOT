"""
SKORMAgency - Music cog (Lavalink + wavelink 3.x)
Play music from SoundCloud, YouTube, Spotify, and 100+ sources via Lavalink.

Commands:
  /play <url>       - Play a track or search
  /stop             - Stop playback and clear queue
  /skip             - Skip current track
  /pause            - Pause/resume playback
  /queue            - Show current queue
  /volume <0-500>   - Set volume
  /nowplaying       - Show current track
"""
import asyncio
import json
import logging
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import wavelink

from bot.config import EMBED_COLOR, FOOTER_TEXT, BRAND_NAME
from bot.cogs import db as music_db

log = logging.getLogger("skorm.music")


class MusicQueue:
    """Per-guild music queue wrapper with history support."""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self._queue: list[wavelink.Playable] = []
        self._history: list[wavelink.Playable] = []

    @property
    def is_empty(self) -> bool:
        return len(self._queue) == 0

    @property
    def length(self) -> int:
        return len(self._queue)

    @property
    def history_length(self) -> int:
        return len(self._history)

    def put(self, track: wavelink.Playable) -> None:
        self._queue.append(track)

    def get(self) -> Optional[wavelink.Playable]:
        if self._queue:
            return self._queue.pop(0)
        return None

    def clear(self) -> None:
        self._queue.clear()
        self._history.clear()

    def peek(self) -> Optional[wavelink.Playable]:
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


def format_track(track: wavelink.Playable, index: int = 0) -> str:
    """Format a track for display."""
    duration = track.length // 1000 if track.length else 0
    minutes = duration // 60
    seconds = duration % 60
    return (
        f"**{index}. [{track.title}]({track.uri})** — {track.author}\n"
        f"   ⏱ {minutes}:{seconds:02d}"
    )


def create_embed(title: str = None, description: str = None, color: int = EMBED_COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


class MusicCog(commands.Cog):
    """Music playback via Lavalink."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._save_task = None

    def cog_unload(self) -> None:
        _queues.clear()
        # Save state on unload
        asyncio.create_task(self._save_all_states())

    async def cog_load(self) -> None:
        """Start periodic state save task."""
        self._save_task = asyncio.create_task(self._periodic_save())

    async def _periodic_save(self) -> None:
        """Save music state every 30 seconds."""
        import asyncio
        while True:
            await asyncio.sleep(30)
            await self._save_all_states()

    async def _save_all_states(self) -> None:
        """Save music state for all guilds."""
        for guild_id, queue in _queues.items():
            if queue.is_empty and not queue._history:
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
        volume = 100
        voice_channel_id = None

        if player:
            if player.current:
                current_track_data = self._serialize_track(player.current)
                position = player.position if hasattr(player, 'position') else 0
                is_paused = player.paused
                volume = player.volume if hasattr(player, 'volume') else 100
            if player.connected:
                # Find voice channel from guild
                guild = self.bot.get_guild(guild_id)
                if guild:
                    vc = guild.voice_channels and next((v for v in guild.voice_channels if v.me), None)
                    if vc:
                        voice_channel_id = vc.id

        # Serialize queue
        queue_data = [self._serialize_track(t) for t in queue._queue]
        history_data = [self._serialize_track(t) for t in queue._history]

        await music_db.save_music_state(guild_id, current_track_data, position, is_paused, volume, voice_channel_id)
        await music_db.save_music_queue(guild_id, queue_data)
        await music_db.save_music_history(guild_id, history_data)

    @staticmethod
    def _serialize_track(track: wavelink.Playable) -> str:
        """Serialize a track to JSON string."""
        return json.dumps({
            "identifier": track.identifier,
            "title": track.title,
            "author": track.author,
            "uri": track.uri,
            "length": track.length,
            "is_stream": track.is_stream,
        })

    @staticmethod
    def _deserialize_track(data: str) -> dict:
        """Deserialize track data from JSON string."""
        return json.loads(data)

    def _get_player_by_id(self, guild_id: int) -> wavelink.Player | None:
        """Get player by guild ID without needing Guild object."""
        pool = self.bot.wavelink
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

                # Restore queue from DB
                queue_rows = await music_db.get_music_queue(guild_id)
                for row in queue_rows:
                    track_data = self._deserialize_track(row["track_data"])
                    # We need to load the track via Lavalink to get a Playable object
                    # For now, store the data and load on demand
                    pass

                # Restore history from DB
                history_rows = await music_db.get_music_history(guild_id)
                for row in history_rows:
                    pass  # Same approach

                # Restore current track if exists
                if state["current_track_data"]:
                    current_data = self._deserialize_track(state["current_track_data"])
                    log.info("Restoring music state for guild %s: %s", guild_id, current_data.get("title"))

                    # Connect to voice channel if it exists
                    voice_channel = guild.get_channel(state["voice_channel_id"])
                    if voice_channel:
                        try:
                            player = await self._ensure_player(guild, voice_channel)
                            # Load and play the track
                            pool = self.bot.wavelink
                            tracks = await pool.fetch_tracks(current_data.get("uri", ""))
                            if tracks:
                                track = tracks[0]
                                await player.play(track)
                                if state["volume"] != 100:
                                    await player.set_volume(state["volume"])
                                log.info("Restored playback: %s", track.title)
                        except Exception as exc:
                            log.error("Failed to restore playback for guild %s: %s", guild_id, exc)

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

        if queue.is_empty:
            log.info("Queue empty, stopping player in guild %s", guild_id)
            await player.stop()
            return

        next_track = queue.get()
        if next_track:
            log.info("Auto-playing next track from queue: %s", next_track.title)
            await player.play(next_track)

    @commands.Cog.listener("on_wavelink_track_stuck")
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload) -> None:
        log.warning("Track stuck: %s", payload.track.title)

    @commands.Cog.listener("on_wavelink_track_exception")
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload) -> None:
        log.error("Lavalink track exception: %s", payload.exception)

    # --- Helper to get player ---

    def _get_player(self, guild: discord.Guild) -> wavelink.Player | None:
        pool = self.bot.wavelink
        node = pool.get_node()
        return node.get_player(guild.id)

    async def _ensure_player(self, guild: discord.Guild, voice_channel: discord.VoiceChannel) -> wavelink.Player:
        """Get existing player or connect to voice channel."""
        player = self._get_player(guild)
        if player and player.connected:
            return player

        # Connect to voice channel - wavelink 3.x creates player automatically
        await voice_channel.connect(cls=wavelink.Player)
        # After connect, get the player from node
        player = self._get_player(guild)
        if player is None:
            raise RuntimeError("Player not created after voice connect")
        return player

    # --- Slash commands ---

    @app_commands.command(name="play", description="Joue une musique (SoundCloud, YouTube, Spotify, etc.)")
    @app_commands.describe(query="URL, recherche, ou numéro de la file d'attente")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ Cette commande ne fonctionne que dans un serveur.", ephemeral=True)
            return

        # Check voice connection
        voice_channel = interaction.user.voice.channel if interaction.user.voice else None
        if not voice_channel:
            await interaction.response.send_message("❌ Rejoins d'abord un salon vocal !", ephemeral=True)
            return

        await interaction.response.defer()

        # Get or create player
        try:
            player = await self._ensure_player(guild, voice_channel)
        except Exception as exc:
            await interaction.followup.send(f"❌ Impossible de rejoindre le salon vocal : {exc}")
            return

        # Check if query is a number (play from queue by index)
        query_str = query.strip()
        queue = get_queue(guild.id)

        if query_str.isdigit():
            index = int(query_str)
            if index < 1 or index > queue.length:
                await interaction.followup.send(f"❌ Index invalide. La file contient {queue.length} piste(s). Utilise `/queue` pour voir la liste.")
                return

            # Get track at index (1-based)
            track = queue._queue.pop(index - 1)
            log.info("Playing track #%d from queue: %s", index, track.title)

            if player.playing:
                # Save current track to history
                if player.current:
                    queue.push_history(player.current)
                await player.play(track)
            else:
                await player.play(track)

            await interaction.followup.send(f"🎵 Lecture de la piste #{index} :\n{format_track(track)}")
            return

        # Search for track
        pool = self.bot.wavelink
        log.info("Music search query: %s", query_str[:100])
        
        try:
            tracks = await pool.fetch_tracks(query_str)
        except Exception as search_exc:
            log.error("Lavalink search failed for '%s': %s", query_str[:100], search_exc, exc_info=True)
            await interaction.followup.send(f"❌ Erreur lors de la recherche : {search_exc}")
            return

        log.info("Search returned %d result(s) for: %s", len(tracks) if tracks else 0, query_str[:100])
        
        if not tracks:
            log.warning("No tracks found for query: %s", query_str[:100])
            await interaction.followup.send("❌ Aucun résultat trouvé. Vérifie que l'URL est valide (Spotify, YouTube, SoundCloud, etc.).")
            return

        track = tracks[0]
        queue = get_queue(guild.id)

        if player.playing:
            queue.put(track)
            await interaction.followup.send(
                f"✅ Ajouté à la file :\n{format_track(track, queue.length)}"
            )
        else:
            await player.play(track)
            await interaction.followup.send(
                f"🎵 En lecture :\n{format_track(track)}"
            )
        
        # Save state immediately after adding track
        await self._save_state(guild.id)

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
        await player.stop()
        await player.disconnect()
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

        # Save current track to history if playing
        if player.current:
            queue.push_history(player.current)

        prev_track = queue.get_previous()
        if prev_track:
            log.info("Playing previous track: %s", prev_track.title)
            await player.play(prev_track)
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
            await player.skip()
            await interaction.response.send_message("⏭ Piste suivante (file vide).")
            return

        # Play next from queue
        next_track = queue.get()
        if next_track:
            log.info("Skipping to next queued track: %s", next_track.title)
            await player.play(next_track)
            await interaction.response.send_message(f"⏭ Lecture suivante :\n{format_track(next_track)}")
        else:
            await player.skip()
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

        if player.paused:
            await player.pause(False)
            await interaction.response.send_message("▶ Lecture reprise.")
        else:
            await player.pause(True)
            await interaction.response.send_message("⏸ Lecture en pause.")

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
            for i, track in enumerate(queue._queue, start=1):
                duration = track.length // 1000 if track.length else 0
                minutes = duration // 60
                seconds = duration % 60
                lines.append(f"**{i}. [{track.title}]({track.uri})** — {track.author}\n   ⏱ {minutes}:{seconds:02d}")
        else:
            lines.append("*Aucune piste en attente.*")

        description = "\n\n".join(lines)
        embed = create_embed(
            title=f"🎵 File d'attente — {BRAND_NAME}",
            description=description[:4000],
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Régle le volume (0-500)")
    @app_commands.describe(level="Volume de 0 à 500 (100 = normal)")
    async def volume(self, interaction: discord.Interaction, level: int) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self._get_player(guild)

        if player is None or not player.connected:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        level = max(0, min(500, level))
        await player.set_volume(level)
        await interaction.response.send_message(f"🔊 Volume réglé à {level}%.")

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
