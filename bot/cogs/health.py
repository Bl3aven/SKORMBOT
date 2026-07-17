"""
SKORMBOT - Health check cog

Provides /health slash command that reports the status of all bot services.
All checks are non-destructive and do not modify channels, categories, or permissions.

Uses only stdlib for HTTP checks (urllib) to avoid aiohttp dependency issues.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import (
    BRAND_NAME,
    COMFYUI_IMAGE_API_ENDPOINT,
    COMFYUI_IMAGE_API_KEY,
    COMFYUI_VIDEO_API_ENDPOINT,
    COMFYUI_VIDEO_API_KEY,
    FOOTER_TEXT,
    LAVALINK_HOST,
    LAVALINK_PASSWORD,
    LAVALINK_PORT,
    OXEEGEN_API_ENDPOINT,
    OXEEGEN_API_KEY,
    OXEEGEN_MODEL,
    SERVER_ID,
)
from bot.cogs import db as db_module
from bot.cogs.utils import create_embed

log = logging.getLogger("skorm.health")

# Expected cogs (tickets is intentionally disabled)
EXPECTED_COGS = [
    "VerificationCog",
    "AutoRoleCog",
    "MusicCog",
    "ImageGenerationCog",
    "VideoGenerationCog",
    "VoiceRecordCog",
    "AIChatCog",
    "RemindersCog",
    "WelcomeCog",
    "RoleSelectionCog",
    "ModerationCog",
    "AntispamCog",
    "LoggingCog",
    "HealthCog",
    # SetupCog is loaded but /setup command is disabled
    "SetupCog",
]

# Cogs that are intentionally disabled
DISABLED_COGS = [
    "TicketsCog",  # ticket system modifies channels/categories/permissions
]

CHECK_TIMEOUT = 5  # seconds per check


def _status(healthy: bool, detail: str = "") -> str:
    icon = "\U00002705" if healthy else "\u274c"
    return f"{icon} {detail}" if detail else icon


def _warn(detail: str) -> str:
    return f"\u26a0\ufe0f {detail}"


async def _check_db() -> str:
    """Non-destructive DB check."""
    try:
        async with await db_module.get_db() as conn:
            cursor = await conn.execute("SELECT 1")
            await cursor.fetchone()
            await cursor.close()
        return _status(True, "Database reachable")
    except Exception as exc:
        return _status(False, f"DB error: {exc}")


async def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int = CHECK_TIMEOUT) -> int | None:
    """Simple HTTP GET using asyncio + stdlib (no aiohttp dependency)."""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, headers=headers or {})
    try:
        loop = asyncio.get_event_loop()
        # Use a wrapper to run blocking urllib in thread
        def _do():
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
                return resp.getcode()
            except urllib.error.HTTPError as e:
                return e.code
            except Exception:
                return None
        return await loop.run_in_executor(None, _do)
    except Exception:
        return None


async def _check_lavalink() -> str:
    """Check Lavalink connectivity."""
    try:
        url = f"http://{LAVALINK_HOST}:{LAVALINK_PORT}/version"
        headers = {"Authorization": LAVALINK_PASSWORD}
        code = await _http_get(url, headers)
        if code == 200:
            return _status(True, "Lavalink connected")
        elif code is not None:
            return _status(False, f"Lavalink HTTP {code}")
        else:
            return _warn("Lavalink unreachable")
    except Exception as exc:
        return _warn(f"Lavalink check failed: {exc}")


async def _check_oxeegen() -> str:
    """Check Oxeegen AI API."""
    if not OXEEGEN_API_KEY:
        return _warn("Oxeegen API key not configured")
    try:
        url = f"{OXEEGEN_API_ENDPOINT}/models"
        headers = {"Authorization": f"Bearer {OXEEGEN_API_KEY}"}
        code = await _http_get(url, headers)
        if code == 200:
            return _status(True, f"Oxeegen OK ({OXEEGEN_MODEL})")
        elif code is not None:
            return _status(False, f"Oxeegen HTTP {code}")
        else:
            return _warn("Oxeegen unreachable")
    except Exception as exc:
        return _warn(f"Oxeegen check failed: {exc}")


async def _check_comfyui_image() -> str:
    """Check ComfyUI image generation API."""
    if not COMFYUI_IMAGE_API_KEY:
        return _warn("ComfyUI image API key not configured")
    try:
        url = f"{COMFYUI_IMAGE_API_ENDPOINT}/status"
        headers = {"Authorization": f"Bearer {COMFYUI_IMAGE_API_KEY}"}
        code = await _http_get(url, headers)
        if code in (200, 204):
            return _status(True, "ComfyUI image OK")
        elif code is not None:
            return _status(False, f"ComfyUI image HTTP {code}")
        else:
            return _warn("ComfyUI image unreachable")
    except Exception as exc:
        return _warn(f"ComfyUI image check failed: {exc}")


async def _check_comfyui_video() -> str:
    """Check ComfyUI video generation API."""
    if not COMFYUI_VIDEO_API_KEY:
        return _warn("ComfyUI video API key not configured")
    try:
        url = f"{COMFYUI_VIDEO_API_ENDPOINT}/status"
        headers = {"Authorization": f"Bearer {COMFYUI_VIDEO_API_KEY}"}
        code = await _http_get(url, headers)
        if code in (200, 204):
            return _status(True, "ComfyUI video OK")
        elif code is not None:
            return _status(False, f"ComfyUI video HTTP {code}")
        else:
            return _warn("ComfyUI video unreachable")
    except Exception as exc:
        return _warn(f"ComfyUI video check failed: {exc}")


async def _check_stt(bot: commands.Bot) -> str:
    """Check Moonshine STT via VoiceRecordCog."""
    try:
        cog = bot.get_cog("VoiceRecordCog")
        if not cog:
            return _warn("VoiceRecordCog not loaded")
        stt = getattr(cog, "stt", None)
        ready = getattr(stt, "is_ready", False)
        if callable(ready):
            ready = ready()
        if stt and ready:
            return _status(True, "Moonshine STT ready")
        else:
            return _warn("Moonshine STT not ready")
    except Exception as exc:
        return _warn(f"STT check failed: {exc}")


async def _check_reminders(bot: commands.Bot) -> str:
    """Check reminders scheduler."""
    try:
        cog = bot.get_cog("RemindersCog")
        if not cog:
            return _warn("RemindersCog not loaded")
        scheduler = getattr(cog, "scheduler", None)
        if scheduler and scheduler.is_running():
            return _status(True, "Reminders scheduler active")
        else:
            return _warn("Reminders scheduler not running")
    except Exception as exc:
        return _warn(f"Reminders check failed: {exc}")


class HealthCog(commands.Cog):
    """Health check cog — non-destructive service status."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need Administrator permission to use this command."
        else:
            log.warning("Health command failed: %s", error)
            message = "Health check failed before it could run."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="health",
        description="Check the health of all bot services (admin only).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def health(self, interaction: discord.Interaction) -> None:
        """Report status of all bot services."""
        await interaction.response.send_message("Running health checks...", ephemeral=True)

        bot = self.bot
        results: list[str] = []
        start = time.monotonic()

        # 1. Gateway latency
        latency_ms = round(bot.latency * 1000, 1)
        results.append(_status(latency_ms < 500, f"Gateway latency: {latency_ms}ms"))

        # 2. Guild configured
        if SERVER_ID:
            guild = bot.get_guild(SERVER_ID)
            results.append(_status(guild is not None, f"Guild configured: {guild.name if guild else 'NOT FOUND'}"))
        else:
            results.append(_warn("SERVER_ID not configured"))

        # 3. Cogs loaded
        loaded = {c.qualified_name for c in bot.cogs.values() if c.qualified_name}
        missing = [c for c in EXPECTED_COGS if c not in loaded]
        extra = [c for c in loaded if c not in EXPECTED_COGS and c not in DISABLED_COGS]
        total_loaded = len(loaded)
        if not missing and not extra:
            results.append(_status(True, f"All {total_loaded} cogs loaded"))
        else:
            parts = [f"{total_loaded} cogs loaded"]
            if missing:
                parts.append(f"missing: {', '.join(missing)}")
            if extra:
                parts.append(f"extra: {', '.join(extra)}")
            results.append(_status(False, "; ".join(parts)))

        # 4. Database
        results.append(await _check_db())

        # 5. Lavalink
        results.append(await _check_lavalink())

        # 6. Oxeegen AI
        results.append(await _check_oxeegen())

        # 7. ComfyUI Image
        results.append(await _check_comfyui_image())

        # 8. ComfyUI Video
        results.append(await _check_comfyui_video())

        # 9. STT (Moonshine)
        results.append(await _check_stt(bot))

        # 10. Reminders
        results.append(await _check_reminders(bot))

        elapsed = round(time.monotonic() - start, 2)

        # Count statuses
        ok = sum(1 for r in results if r.startswith("\U00002705"))
        fail = sum(1 for r in results if r.startswith("\u274c"))
        warn = sum(1 for r in results if r.startswith("\u26a0"))

        # Build embed
        embed = create_embed(
            title=f"{BRAND_NAME} — Health Report",
            description="\n".join(results),
            color=0x00FF00 if fail == 0 else (0xFFFF00 if warn > 0 else 0xFF0000),
        )

        summary = f"{ok} OK / {warn} WARNING / {fail} FAIL — {elapsed}s"
        embed.add_field(name="Summary", value=summary, inline=False)
        embed.set_footer(text=FOOTER_TEXT, icon_url=None)

        await interaction.followup.send(embed=embed, ephemeral=True)
        log.info("Health check completed in %.2fs: %d OK, %d WARN, %d FAIL", elapsed, ok, warn, fail)
