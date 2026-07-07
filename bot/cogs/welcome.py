"""
SKORMAgency - Welcome cog
Sends welcome DMs and verifies new members through a reaction in │rules.
"""
import logging

import discord
from discord.ext import commands

from bot.cogs.utils import (
    create_embed,
    get_channel_by_name,
    get_role_by_name,
)

log = logging.getLogger("skorm.welcome")


WELCOME_CHANNEL_NAME = "│welcome"
RULES_CHANNEL_NAME = "│rules"
ROLES_CHANNEL_NAME = "│claim-your-roles"
VERIFY_EMOJI = "✅"


class WelcomeCog(commands.Cog):
    """Welcome + verification flow via reaction in │rules."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._verify_message_id: int | None = None

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Find or create the persistent verification message in │rules."""
        from bot.config import SERVER_ID
        if not SERVER_ID:
            return
        guild = self.bot.get_guild(SERVER_ID)
        if not guild:
            return

        rules_channel = get_channel_by_name(guild, RULES_CHANNEL_NAME)
        if not rules_channel:
            return

        # Try to find existing verification message (by bot, with Rules title)
        try:
            async for msg in rules_channel.history(limit=50):
                if msg.author == self.bot.user and msg.embeds and "Rules" in msg.embeds[0].title:
                    self._verify_message_id = msg.id
                    # Ensure ✅ reaction is present
                    if not any(str(r.emoji) == VERIFY_EMOJI for r in msg.reactions):
                        await msg.add_reaction(VERIFY_EMOJI)
                    log.info("Found existing verification message %s in │rules", msg.id)
                    return
        except Exception as exc:
            log.warning("Failed to search for verification message: %s", exc)

        # Create verification message if not found
        try:
            verify_embed = create_embed(
                title="📖 SKORM Rules",
                description=(
                    "Welcome to **SKORM** !\n\n"
                    "To access the server, react with ✅ below\n"
                    "to accept the rules."
                ),
                color=0xFFFFFF,
            )
            msg = await rules_channel.send(embed=verify_embed)
            await msg.add_reaction(VERIFY_EMOJI)
            self._verify_message_id = msg.id
            log.info("Created verification message %s in │rules", msg.id)
        except Exception as exc:
            log.error("Failed to create verification message: %s", exc)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        welcome_channel = get_channel_by_name(guild, WELCOME_CHANNEL_NAME)
        rules_channel = get_channel_by_name(guild, RULES_CHANNEL_NAME)
        roles_channel = get_channel_by_name(guild, ROLES_CHANNEL_NAME)

        # 1. Post welcome message in │welcome
        if welcome_channel:
            try:
                embed = create_embed(
                    title=f"🌩️ Welcome to SKORM, {member.display_name} !",
                    description=(
                        "**CREATE. CONNECT. DEVELOP.**\n\n"
                        f"{member.mention} just joined the server !"
                    ),
                    color=0xFFFFFF,
                )
                await welcome_channel.send(embed=embed)
            except Exception as exc:
                log.error("Failed to send welcome message: %s", exc)

        # 2. Send DM with welcome + 2 tasks
        try:
            dm_embed = create_embed(
                title="🌩️ Welcome to SKORM !",
                description=(
                    "**CREATE. CONNECT. DEVELOP.**\n\n"
                    "You just joined the official SKORM server.\n\n"
                    "To access the server, complete these 2 steps :\n\n"
                    "1️⃣ **Accept the rules**\n"
                    f"   Go to <#{rules_channel.id}> and react with ✅\n"
                    if rules_channel else "   Go to │rules and react with ✅\n"
                    "2️⃣ **Choose your role**\n"
                    f"   Go to <#{roles_channel.id}> and select your path"
                    if roles_channel else "   Go to │claim-your-roles and select your path",
                ),
                color=0xFFFFFF,
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            log.warning("DM blocked for %s", member)
        except Exception as exc:
            log.error("Failed to send DM to %s: %s", member, exc)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """Handle verification using raw events (works without message cache)."""
        if payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        # Check emoji
        emoji_str = str(payload.emoji)
        emoji_name = getattr(payload.emoji, 'name', '')
        is_verify = (
            emoji_str == VERIFY_EMOJI or
            emoji_name == VERIFY_EMOJI or
            emoji_str == "\U00002705" or
            emoji_str == "\u2705" or
            "white_check_mark" in emoji_name or
            "check" in emoji_name.lower()
        )
        if not is_verify:
            return

        # Find │rules channel
        rules_channel = get_channel_by_name(guild, RULES_CHANNEL_NAME)
        if rules_channel is None:
            log.warning("│rules channel not found for verification")
            return
        if payload.channel_id != rules_channel.id:
            return

        # Check this is the verification message
        if self._verify_message_id and payload.message_id != self._verify_message_id:
            return

        log.info("Verification reaction from %s in channel %s", member.display_name, rules_channel.name)

        verified_role = get_role_by_name(guild, "Verified")
        if verified_role is None:
            log.error("Verified role not found in guild %s", guild.name)
            return

        try:
            await member.add_roles(verified_role, reason="SKORM verification (reaction)")
            log.info("Granted Verified role to %s", member.display_name)
        except discord.Forbidden:
            log.error("Forbidden to add role to %s", member.display_name)
            return
        except Exception as exc:
            log.error("Verification failed for %s: %s", member.display_name, exc)
            return

        # Remove reaction after verification
        try:
            await rules_channel.remove_reaction(payload.emoji, member, payload.message_id)
        except Exception:
            pass

        # Send confirmation in DM
        roles_channel = get_channel_by_name(guild, ROLES_CHANNEL_NAME)
        try:
            confirm_embed = create_embed(
                title="✅ Rules accepted !",
                description=(
                    "You are now verified on SKORM.\n\n"
                    "One step remaining :\n\n"
                    f"🎭 **Choose your role** in <#{roles_channel.id}>"
                    if roles_channel else "🎭 Choose your role in │claim-your-roles",
                ),
                color=0x00FF00,
            )
            await member.send(embed=confirm_embed)
        except discord.Forbidden:
            pass
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))