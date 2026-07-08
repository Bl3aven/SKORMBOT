"""
SKORMAgency - Voice Recording & Transcription cog
Records voice channel conversations, transcribes with Moonshine STT, and summarizes with Oxee-flash.

Commands:
  /recordconv  - Start recording the current voice channel
  /stoprecord  - Manually stop recording (or recording stops when last member leaves)
"""
import asyncio
import logging
import struct
import time
from datetime import datetime
from typing import Optional

import aiohttp
import discord
import numpy as np
import opuslib
from discord import app_commands
from discord.ext import commands

from bot.config import (
    OXEEGEN_API_ENDPOINT, OXEEGEN_API_KEY, OXEEGEN_MODEL,
    COLOR_WHITE, COLOR_GRAY, COLOR_BLACK, EMBED_COLOR, FOOTER_TEXT, BRAND_NAME,
)
from bot.cogs.utils import create_embed
from bot.cogs.stt_client import MoonshineSTT

log = logging.getLogger("skorm.voice_record")

# Opus decode frame size at 48kHz
OPUS_FRAME_SIZE = 960  # samples per channel at 20ms frame, 48kHz
OPUS_CHANNELS = 2  # Discord sends stereo
OPUS_SAMPLE_RATE = 48000


# Summary prompt for Oxee-flash
SUMMARY_SYSTEM_PROMPT = """You are a conversation summarizer for a Discord voice channel recording.

YOUR TASK:
- Read the raw transcription of a voice conversation
- Produce a structured, concise summary in the SAME LANGUAGE as the conversation

OUTPUT FORMAT:
**📋 Participants:** List speakers identified (or "Multiple speakers" if unknown)
**⏱ Duration:** Recording duration
**🎯 Topics:** Key subjects discussed (bullet points)
**✅ Decisions:** Any decisions or agreements made
**📝 Action Items:** Tasks or follow-ups mentioned
**💡 Key Takeaways:** 2-3 sentence overall summary

RULES:
- Keep the summary under 1500 characters
- Use Discord markdown formatting
- Be concise but informative
- If the conversation is short or has little content, note that honestly
- If the transcription seems garbled or unclear, mention it"""


class RecordingSession:
    """Manages a single voice recording session."""

    def __init__(self, guild_id: int, voice_channel: discord.VoiceChannel,
                 text_channel: discord.TextChannel, user: discord.User):
        self.guild_id = guild_id
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        self.user = user
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.audio_buffer: bytearray = bytearray()
        self.speakers: set[int] = set()  # User IDs who spoke
        self.is_recording: bool = False
        self.status_message: Optional[discord.Message] = None

        # Opus decoder per speaker (each needs its own decoder state)
        self.decoders: dict[int, object] = {}  # opuslib.Decoder instances

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time if self.start_time else 0

    @property
    def duration_str(self) -> str:
        secs = int(self.duration_seconds)
        mins = secs // 60
        secs = secs % 60
        return f"{mins}m{secs:02d}"

    def get_decoder(self, user_id: int) -> opuslib.Decoder:
        """Get or create an Opus decoder for a speaker."""
        if user_id not in self.decoders:
            self.decoders[user_id] = opuslib.Decoder(OPUS_SAMPLE_RATE, OPUS_CHANNELS)
        return self.decoders[user_id]

    def _decode_opus_packet(self, user_id: int, opus_data: bytes) -> Optional[bytes]:
        """Decode an Opus packet to mono PCM bytes (runs in thread pool)."""
        try:
            decoder = self.get_decoder(user_id)
            pcm = decoder.decode(opus_data, OPUS_FRAME_SIZE)

            # Convert stereo to mono using numpy (fast, vectorized)
            samples = np.frombuffer(pcm, dtype=np.int16)
            # Reshape to (frames, channels), average channels, flatten
            samples = samples.reshape(-1, OPUS_CHANNELS).mean(axis=1).astype(np.int16)
            return samples.tobytes()
        except Exception as e:
            log.debug("Failed to decode Opus packet for user %d: %s", user_id, e)
            return None

    async def add_opus_packet(self, user_id: int, opus_data: bytes) -> None:
        """Decode an Opus packet in thread pool and append to the audio buffer."""
        loop = asyncio.get_event_loop()
        pcm_bytes = await loop.run_in_executor(None, self._decode_opus_packet, user_id, opus_data)
        if pcm_bytes:
            self.audio_buffer.extend(pcm_bytes)
            self.speakers.add(user_id)


# Active recording sessions per guild
_active_sessions: dict[int, RecordingSession] = {}


class VoiceRecordCog(commands.Cog):
    """Voice recording, transcription, and AI summarization."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.session = None
        self.stt = MoonshineSTT()

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()
        # Initialize STT in background
        asyncio.create_task(self._init_stt())

    async def cog_unload(self) -> None:
        if self.session:
            await self.session.close()
        # Stop all active recordings
        await self._stop_all_recordings()

    async def _init_stt(self) -> None:
        """Initialize Moonshine STT in background."""
        try:
            success = await self.stt.initialize()
            if success:
                log.info("Moonshine STT ready for transcription")
            else:
                log.warning("Moonshine STT initialization failed - transcription will be unavailable")
        except Exception as e:
            log.error("STT background init error: %s", e)

    async def _stop_all_recordings(self) -> None:
        """Stop all active recordings on shutdown."""
        for guild_id, session in list(_active_sessions.items()):
            if session.is_recording:
                await self._end_recording(guild_id, reason="Bot shutting down")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Detect when the last member leaves the recording channel."""
        guild_id = member.guild.id

        if guild_id not in _active_sessions:
            return

        session = _active_sessions[guild_id]
        if not session.is_recording:
            return

        # Check if the bot itself is still in the channel
        bot_member = member.guild.me
        if after.channel is None and before.channel == session.voice_channel:
            # A member left the recording channel
            log.info("Member %s left voice channel %s", member.display_name, session.voice_channel.name)

        # Check if bot was disconnected
        if bot_member.voice is None or bot_member.voice.channel != session.voice_channel:
            log.info("Bot disconnected from %s, ending recording", session.voice_channel.name)
            await self._end_recording(guild_id, reason="Bot disconnected from voice channel")
            return

        # Count non-bot members in the channel
        voice_members = [
            m for m in session.voice_channel.members
            if not m.bot and m.id != member.guild.me.id
        ]

        if len(voice_members) == 0 and session.is_recording:
            log.info("No members left in %s, ending recording", session.voice_channel.name)
            await self._end_recording(guild_id, reason="All members left the voice channel")

    async def _join_voice_channel(self, channel: discord.VoiceChannel) -> Optional[discord.VoiceClient]:
        """Join a voice channel."""
        try:
            log.info("Attempting to join voice channel: %s (id=%d) in guild %s",
                    channel.name, channel.id, channel.guild.name)
            voice_client = await channel.connect()
            log.info("Successfully joined voice channel: %s", channel.name)
            return voice_client
        except discord.Forbidden:
            log.error("Forbidden: bot lacks permission to join %s. Check role permissions on the channel/category.", channel.name)
            return None
        except discord.InvalidArgument as e:
            log.error("InvalidArgument joining %s: %s", channel.name, e)
            return None
        except Exception as e:
            log.error("Failed to join voice channel %s: %s (%s)", channel.name, type(e).__name__, e)
            return None

    async def _start_recording(
        self,
        guild: discord.Guild,
        voice_channel: discord.VoiceChannel,
        text_channel: discord.TextChannel,
        user: discord.User,
    ) -> None:
        """Start recording a voice channel."""
        guild_id = guild.id

        # Check for existing session
        if guild_id in _active_sessions and _active_sessions[guild_id].is_recording:
            await text_channel.send(
                embed=create_embed(
                    title="⚠️ Already Recording",
                    description=f"A recording is already active in {voice_channel.mention}.",
                    color=COLOR_GRAY,
                )
            )
            return

        # Create session
        session = RecordingSession(guild_id, voice_channel, text_channel, user)
        session.start_time = time.time()
        session.is_recording = True
        _active_sessions[guild_id] = session

        # Join voice channel
        voice_client = await self._join_voice_channel(voice_channel)
        if voice_client is None:
            session.is_recording = False
            del _active_sessions[guild_id]
            await text_channel.send(
                embed=create_embed(
                    title="❌ Connection Failed",
                    description="Could not join the voice channel. Check bot permissions.",
                    color=COLOR_GRAY,
                )
            )
            return

        # Send status message
        status_embed = create_embed(
            title="🎙️ Recording Started",
            description=(
                f"Recording in **{voice_channel.name}**\n"
                f"Started by {user.mention}\n"
                f"Recording will stop when all members leave the voice channel.\n"
                f"Or use `/stoprecord` to stop manually."
            ),
            color=COLOR_BLACK,
        )
        status_embed.add_field(name="⏱ Duration", value="0m00", inline=True)
        status_embed.add_field(name="👥 Speakers", value="0", inline=True)

        try:
            session.status_message = await text_channel.send(
                embed=status_embed,
            )
        except Exception:
            pass

        # Start audio capture task
        asyncio.create_task(self._capture_audio(guild_id, voice_client))

    def _get_speaker_from_packet(self, voice_client: discord.VoiceClient, packet) -> int:
        """
        Extract the Discord user ID from a voice packet's SSID.

        discord.py maps SSIDs to user IDs internally. We try multiple approaches
        for compatibility across versions.
        """
        packet_ssid = getattr(packet, "ssid", None)
        if packet_ssid is None:
            return 0

        # Approach 1: voice_client._voice_states (dict of user_id -> VoiceState)
        # Each VoiceState has an .ssid attribute
        voice_states = getattr(voice_client, "_voice_states", None)
        if isinstance(voice_states, dict):
            for user_id, state in voice_states.items():
                if getattr(state, "ssid", None) == packet_ssid:
                    return user_id

        # Approach 2: voice_client.gateway._voice_states (list of dicts)
        gateway = getattr(voice_client, "gateway", None)
        if gateway:
            gw_voice_states = getattr(gateway, "_voice_states", None)
            if isinstance(gw_voice_states, list):
                for vs in gw_voice_states:
                    if isinstance(vs, dict) and vs.get("ssid") == packet_ssid:
                        return vs.get("user_id", 0)
            elif isinstance(gw_voice_states, dict):
                for user_id, state in gw_voice_states.items():
                    if isinstance(state, dict) and state.get("ssid") == packet_ssid:
                        return user_id
                    if getattr(state, "ssid", None) == packet_ssid:
                        return user_id

        # Fallback: can't resolve speaker
        return 0

    async def _capture_audio(self, guild_id: int, voice_client: discord.VoiceClient) -> None:
        """Continuously capture audio packets from the voice channel."""
        session = _active_sessions.get(guild_id)
        if not session:
            return

        log.info("Starting audio capture for guild %d", guild_id)
        last_update = time.time()
        packets_count = 0

        try:
            while session.is_recording:
                try:
                    # Wait for voice data (non-blocking with timeout)
                    packet = await asyncio.wait_for(voice_client.recv(), timeout=1.0)

                    if packet is None:
                        continue

                    # Get Opus data from packet
                    # discord.py VoicePacket: .data or .voice_data contains raw Opus bytes
                    opus_data = getattr(packet, "voice_data", None) or getattr(packet, "data", None)
                    if not opus_data:
                        continue

                    # Resolve speaker user ID from SSID
                    speaker_id = self._get_speaker_from_packet(voice_client, packet)
                    await session.add_opus_packet(speaker_id, opus_data)
                    packets_count += 1

                    # Update status message every 10 seconds
                    now = time.time()
                    if now - last_update > 10 and session.status_message:
                        try:
                            embed = session.status_message.embeds[0]
                            embed.fields[0].value = session.duration_str
                            embed.fields[1].value = str(len(session.speakers))
                            await session.status_message.edit(embed=embed)
                            last_update = now
                        except Exception:
                            pass

                except asyncio.TimeoutError:
                    # No data this second — check if we should stop
                    if not session.is_recording:
                        break
                    continue
                except Exception as e:
                    log.debug("Packet capture error: %s", str(e))
                    if not session.is_recording:
                        break

            log.info("Capture ended: %d packets from %d speakers", packets_count, len(session.speakers))

        finally:
            # Disconnect from voice channel
            try:
                await voice_client.disconnect()
            except Exception:
                pass
            log.info("Audio capture stopped for guild %d", guild_id)

    async def _end_recording(self, guild_id: int, reason: str = "") -> None:
        """End recording, transcribe, summarize, and post results."""
        session = _active_sessions.pop(guild_id, None)
        if not session:
            return

        session.is_recording = False
        session.end_time = time.time()

        log.info("Ending recording for guild %d: %s", guild_id, reason)

        # Update status message
        if session.status_message:
            try:
                embed = create_embed(
                    title="⏹ Recording Stopped",
                    description=(
                        f"Duration: **{session.duration_str}**\n"
                        f"Speakers: **{len(session.speakers)}**\n"
                        f"Audio size: **{len(session.audio_buffer) / 1024:.0f} KB**\n"
                        f"Reason: {reason}"
                    ),
                    color=COLOR_GRAY,
                )
                await session.status_message.edit(embed=embed)
            except Exception:
                pass

        # Check if we have audio data
        if len(session.audio_buffer) < 1024:
            # Too little audio, skip transcription
            msg = f"⏹ Recording stopped after **{session.duration_str}**.\n"
            msg += "⚠️ Not enough audio captured to transcribe."
            if reason:
                msg += f"\n_Reason: {reason}_"
            await session.text_channel.send(msg)
            return

        # Start transcription
        transcribing_msg = await session.text_channel.send(
            embed=create_embed(
                title="📝 Transcribing...",
                description=(
                    f"Processing **{session.duration_str}** of audio "
                    f"from **{len(session.speakers)}** speaker(s)...\n"
                    f"This may take a moment."
                ),
                color=COLOR_GRAY,
            )
        )

        # Transcribe
        transcript = await self.stt.transcribe_audio(
            audio_data=bytes(session.audio_buffer),
            sample_rate=OPUS_SAMPLE_RATE,
        )

        if not transcript or transcript.startswith("["):
            # Transcription failed or no speech
            await transcribing_msg.edit(
                embed=create_embed(
                    title="⚠️ Transcription Issue",
                    description=(
                        f"Recording: **{session.duration_str}**\n"
                        f"Result: {transcript}"
                    ),
                    color=COLOR_GRAY,
                )
            )
            return

        # Summarize with Oxee-flash
        await transcribing_msg.edit(
            embed=create_embed(
                title="🤖 Summarizing...",
                description="AI is generating a summary of the conversation...",
                color=COLOR_GRAY,
            )
        )

        summary = await self._summarize_transcript(transcript, session, guild_id)

        # Post final result
        await self._post_summary(session, transcript, summary)

        # Delete transcribing message
        try:
            await transcribing_msg.delete()
        except Exception:
            pass

    async def _summarize_transcript(
        self, transcript: str, session: RecordingSession, guild_id: int,
    ) -> str:
        """Send transcript to Oxee-flash for summarization."""
        if not OXEEGEN_API_KEY or not self.session:
            return "[AI summary unavailable - API not configured]"

        # Build participant list
        guild = self.bot.get_guild(guild_id)
        participants = ""
        if guild:
            for uid in session.speakers:
                member = guild.get_member(uid)
                name = member.display_name if member else f"User#{uid}"
                participants += f"- {name}\n"
        if not participants:
            participants = f"- {len(session.speakers)} speaker(s) (names unavailable)\n"

        user_message = (
            f"Duration: {session.duration_str}\n"
            f"Participants:\n{participants}\n\n"
            f"Transcription:\n{transcript}"
        )

        url = f"{OXEEGEN_API_ENDPOINT}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OXEEGEN_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": OXEEGEN_MODEL,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": 2000,
            "temperature": 0.5,
        }

        try:
            async with self.session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    error_text = await resp.text()
                    log.error("Oxeegen summary error %d: %s", resp.status, error_text)
                    return f"[Summary error: API returned {resp.status}]"
        except asyncio.TimeoutError:
            return "[Summary timeout - the conversation may have been too long]"
        except Exception as e:
            log.error("Summary API call failed: %s", e)
            return f"[Summary error: {type(e).__name__}]"

    async def _post_summary(
        self, session: RecordingSession, transcript: str, summary: str,
    ) -> None:
        """Post the final summary and transcript to the text channel."""
        # Main summary embed
        summary_embed = create_embed(
            title="🎙️ Conversation Summary",
            description=summary[:1500],
            color=COLOR_BLACK,
        )
        summary_embed.add_field(
            name="⏱ Duration", value=session.duration_str, inline=True
        )
        summary_embed.add_field(
            name="👥 Speakers", value=str(len(session.speakers)), inline=True
        )
        summary_embed.add_field(
            name="📊 Audio", value=f"{len(session.audio_buffer) / 1024:.0f} KB", inline=True
        )
        summary_embed.set_footer(
            text=f"Recorded by {session.user.display_name} • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

        await session.text_channel.send(embed=summary_embed)

        # Full transcript in a spoiler (if it's long)
        if len(transcript) > 500:
            transcript_text = f"||📋 **Full Transcript:**\n\n{transcript}||"
            # Split into chunks if needed (Discord limit 2000 chars)
            for i in range(0, len(transcript_text), 1900):
                await session.text_channel.send(transcript_text[i:i + 1900])
        else:
            await session.text_channel.send(f"📋 **Transcript:**\n\n{transcript}")

    @app_commands.command(name="recordconv", description="Start recording the voice channel conversation")
    async def recordconv(self, interaction: discord.Interaction) -> None:
        """Start recording the current voice channel."""
        await interaction.response.defer(ephemeral=False)

        guild = interaction.guild
        user = interaction.user
        member = interaction.user

        if not guild:
            await interaction.followup.send("This command can only be used in a server.", ephemeral=True)
            return

        # Check if user is in a voice channel
        if not member.voice or not member.voice.channel:
            await interaction.followup.send(
                embed=create_embed(
                    title="❌ Not in Voice Channel",
                    description="You need to be in a voice channel to start recording.",
                    color=COLOR_GRAY,
                )
            )
            return

        voice_channel = member.voice.channel

        # Get the text channel to post results
        # Use the channel where the command was issued
        text_channel = interaction.channel
        if not isinstance(text_channel, (discord.TextChannel, discord.ForumChannel)):
            await interaction.followup.send(
                "Please use this command in a text channel.",
                ephemeral=True,
            )
            return

        # Check permissions (bot needs to connect to voice)
        # Use the voice channel's permissions for the bot member
        if not voice_channel.permissions_for(guild.me).connect:
            await interaction.followup.send(
                embed=create_embed(
                    title="❌ Missing Permissions",
                    description="The bot needs 'Connect' voice permission.",
                    color=COLOR_GRAY,
                )
            )
            return

        # Start recording
        await self._start_recording(guild, voice_channel, text_channel, user)

    @app_commands.command(name="stoprecord", description="Manually stop the current recording")
    async def stoprecord(self, interaction: discord.Interaction) -> None:
        """Manually stop the current recording."""
        guild_id = interaction.guild.id

        if guild_id not in _active_sessions or not _active_sessions[guild_id].is_recording:
            await interaction.response.send_message(
                embed=create_embed(
                    title="⚠️ No Active Recording",
                    description="There is no active recording in this server.",
                    color=COLOR_GRAY,
                ),
                ephemeral=False,
            )
            return

        # Signal the capture loop to stop immediately (before deferring)
        _active_sessions[guild_id].is_recording = False

        await interaction.response.defer(ephemeral=False)
        await self._end_recording(guild_id, reason="Stopped manually by " + interaction.user.display_name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceRecordCog(bot))
