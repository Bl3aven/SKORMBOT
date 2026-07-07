"""
SKORMAgency - Main entry point
Bootstraps the Discord bot, loads all cogs and synchronises slash commands.
"""
import asyncio
import logging
import sys
import traceback

import discord
from discord.ext import commands

from bot.config import (
    BOT_TOKEN, BRAND_NAME, BRAND_TAGLINE, SERVER_ID, OWNER_ID,
    LAVALINK_HOST, LAVALINK_PORT, LAVALINK_PASSWORD,
)
from bot.cogs import db

import wavelink


# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("skorm")


# === Bot setup ===
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# === Cogs to load ===
COGS = [
    "bot.cogs.setup",
    "bot.cogs.welcome",
    "bot.cogs.role_selection",
    "bot.cogs.tickets",
    "bot.cogs.logging_cog",
    "bot.cogs.antispam",
    "bot.cogs.reminders",
    "bot.cogs.moderation",
    "bot.cogs.music",
]


async def load_cogs() -> None:
    for ext in COGS:
        try:
            await bot.load_extension(ext)
            log.info("Loaded cog: %s", ext)
        except Exception as exc:
            log.error("Failed to load cog %s: %s", ext, exc)
            traceback.print_exc()

    # Connect to Lavalink
    try:
        bot.wavelink = wavelink.Pool(
            nodes=[
                wavelink.Node(
                    uri=f"http://{LAVALINK_HOST}:{LAVALINK_PORT}",
                    password=LAVALINK_PASSWORD,
                )
            ]
        )
        log.info("Connected to Lavalink at %s:%s", LAVALINK_HOST, LAVALINK_PORT)
    except Exception as exc:
        log.error("Failed to connect to Lavalink: %s", exc)
        bot.wavelink = None


@bot.event
async def on_ready() -> None:
    log.info("=" * 60)
    log.info("%s bot online as %s (id=%s)", BRAND_NAME, bot.user, bot.user.id)
    log.info("Tagline: %s", BRAND_TAGLINE)
    log.info("Connected to %d guild(s):", len(bot.guilds))
    for guild in bot.guilds:
        log.info("  - %s (id=%s, members=%d)", guild.name, guild.id, guild.member_count)
    log.info("=" * 60)

    # Initialise database
    try:
        await db.init_db()
        log.info("Database initialised at %s", db.DB_PATH)
    except Exception as exc:
        log.error("Database initialisation failed: %s", exc)

    # Auto-apply permissions on startup
    try:
        guild = bot.get_guild(SERVER_ID) if SERVER_ID else None
        if guild:
            setup_cog = bot.get_cog("SetupCog")
            if setup_cog:
                log.info("Auto-applying permissions to guild %s", guild.name)
                role_map = {r.name: r for r in guild.roles}
                category_map = {c.name: c for c in guild.categories}
                await setup_cog._apply_permissions(guild, category_map, role_map)
                await setup_cog._secure_voice_channels(guild, role_map, {"errors": []})
                log.info("Permissions auto-applied successfully")
    except Exception as exc:
        log.error("Failed to auto-apply permissions: %s", exc)

    # Sync slash commands (guild scope when SERVER_ID is configured, global otherwise)
    try:
        if SERVER_ID:
            guild_obj = discord.Object(id=SERVER_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            log.info("Synced %d slash command(s) to guild %s", len(synced), SERVER_ID)
        else:
            synced = await bot.tree.sync()
            log.info("Synced %d global slash command(s)", len(synced))
    except Exception as exc:
        log.error("Failed to sync commands: %s", exc)

    # Presence
    try:
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{BRAND_TAGLINE}",
        )
        await bot.change_presence(activity=activity)
    except Exception:
        pass


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """Fallback error handler for prefix commands."""
    if isinstance(error, commands.CommandNotFound):
        return
    log.error("Command error in %s: %s", ctx.command, error)
    try:
        await ctx.send(f"❌ Erreur : `{error}`")
    except Exception:
        pass


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    """Error handler for slash commands."""
    log.error("Slash command error: %s", error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                f"❌ Erreur : `{error}`", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Erreur : `{error}`", ephemeral=True
            )
    except Exception:
        pass


async def main() -> None:
    if not BOT_TOKEN:
        log.critical("BOT_TOKEN not configured. Set it in .env or environment.")
        sys.exit(1)

    async with bot:
        await load_cogs()
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down…")
    except Exception as exc:
        log.critical("Fatal error: %s", exc)
        traceback.print_exc()