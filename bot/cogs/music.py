"""
SKORMAgency - Music cog (Lavalink + wavelink)
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
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import wavelink

from bot.config import EMBED_COLOR, FOOTER_TEXT, BRAND_NAME

log = logging.getLogger("skorm.music")


class MusicQueue:
    """Per-guild music queue wrapper around wavelink."""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self._queue: list[wavelink.Track] = []

    @property
    def is_empty(self) -> bool:
        return len(self._queue) == 0

    @property
    def length(self) -> int:
        return len(self._queue)

    def put(self, track: wavelink.Track) -> None:
        self._queue.append(track)

    def get(self) -> Optional[wavelink.Track]:
        if self._queue:
            return self._queue.pop(0)
        return None

    def clear(self) -> None:
        self._queue.clear()

    def peek(self) -> Optional[wavelink.Track]:
        if self._queue:
            return self._queue[0]
        return None


# Per-guild queues
_queues: dict[int, MusicQueue] = {}


def get_queue(guild_id: int) -> MusicQueue:
    if guild_id not in _queues:
        _queues[guild_id] = MusicQueue(guild_id)
    return _queues[guild_id]


def format_track(track: wavelink.Track, index: int = 0) -> str:
    """Format a track for display."""
    duration = track.duration // 1000 if track.duration else 0
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

    def cog_unload(self) -> None:
        _queues.clear()

    # --- Lavalink event: track finished ---
    @wavelink.event
    async def track_end(self, player: wavelink.Player, track: wavelink.Track, reason: str) -> None:
        """Play next track from queue when current track ends."""
        guild_id = player.guild.id
        queue = get_queue(guild_id)

        if queue.is_empty:
            await player.stop()
            # Notify in voice channel text channel if possible
            vc = player.voice_client
            if vc and vc.channel:
                try:
                    await vc.channel.send("🎵 File d'attente vide. Utilise `/play <url>` pour lancer de la musique !")
                except Exception:
                    pass
            return

        next_track = queue.get()
        if next_track:
            await player.play(next_track)

    @wavelink.event
    async def track_stuck(self, player: wavelink.Player, track: wavelink.Track, threshold: int) -> None:
        log.warning("Track stuck: %s", track.title)

    @wavelink.event
    async def exception(self, player: wavelink.Player, exception: Exception) -> None:
        log.error("Lavalink exception: %s", exception)

    # --- Slash commands ---

    @app_commands.command(name="play", description="Joue une musique (SoundCloud, YouTube, Spotify, etc.)")
    @app_commands.describe(query="URL ou recherche (ex: https://on.soundcloud.com/xxx)")
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
        player = self.bot.wavelink.get_player(guild)
        if not player.is_connected:
            try:
                await voice_channel.connect(cls=lambda vc: wavelink.Player(vc, guild))
            except Exception as exc:
                await interaction.followup.send(f"❌ Impossible de rejoindre le salon vocal : {exc}")
                return
            player = self.bot.wavelink.get_player(guild)

        # Search for track
        query_str = query.strip()
        tracks = await player.node.search(query_str, source_managers=wavelink.SearchType.AUTO_SEARCH)

        if not tracks:
            await interaction.followup.send("❌ Aucun résultat trouvé.")
            return

        track = tracks[0].track
        queue = get_queue(guild.id)

        if player.is_playing:
            queue.put(track)
            await interaction.followup.send(
                f"✅ Ajouté à la file :\n{format_track(track, queue.length)}"
            )
        else:
            await player.play(track)
            await interaction.followup.send(
                f"🎵 En lecture :\n{format_track(track)}"
            )

    @app_commands.command(name="stop", description="Arrête la musique et vide la file d'attente")
    async def stop(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self.bot.wavelink.get_player(guild)
        if not player.is_connected:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        get_queue(guild.id).clear()
        await player.stop()
        await player.voice_client.disconnect()
        await interaction.response.send_message("🛑 Musique arrêtée et file d'attente vidée.")

    @app_commands.command(name="skip", description="Passe à la piste suivante")
    async def skip(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self.bot.wavelink.get_player(guild)
        if not player.is_playing:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        await player.skip()
        await interaction.response.send_message("⏭ Piste suivante.")

    @app_commands.command(name="pause", description="Met en pause ou reprend la lecture")
    async def pause(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self.bot.wavelink.get_player(guild)
        if not player.is_connected:
            await interaction.response.send_message("❌ Aucune musique en cours.", ephemeral=True)
            return

        if player.is_paused:
            await player.set_pause(False)
            await interaction.response.send_message("▶ Lecture reprise.")
        else:
            await player.set_pause(True)
            await interaction.response.send_message("⏸ Lecture en pause.")

    @app_commands.command(name="queue", description="Affiche la file d'attente")
    async def queue_cmd(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self.bot.wavelink.get_player(guild)
        queue = get_queue(guild.id)

        if not player.is_playing and queue.is_empty:
            await interaction.response.send_message("🎵 File d'attente vide. Utilise `/play <url>` pour commencer !", ephemeral=True)
            return

        lines = []
        if player.current_track:
            lines.append(f"**🎵 En lecture :**\n{format_track(player.current_track, 0)}")

        for i, track in enumerate(queue._queue, start=1):
            lines.append(format_track(track, i))

        if not lines:
            await interaction.response.send_message("🎵 File d'attente vide.")
            return

        description = "\n\n".join(lines)
        embed = create_embed(
            title=f"🎵 File d'attente — {BRAND_NAME}",
            description=description[:4000],  # Discord embed limit
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Régle le volume (0-500)")
    @app_commands.describe(level="Volume de 0 à 500 (100 = normal)")
    async def volume(self, interaction: discord.Interaction, level: int) -> None:
        guild = interaction.guild
        if guild is None:
            return

        player = self.bot.wavelink.get_player(guild)
        if not player.is_connected:
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

        player = self.bot.wavelink.get_player(guild)
        track = player.current_track

        if not track:
            await interaction.response.send_message("🎵 Aucune musique en cours.", ephemeral=True)
            return

        progress = player.position
        duration = track.duration

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
