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
                    title=f"🌩️ Bienvenue sur SKORM, {member.display_name} !",
                    description=(
                        "**CREATE. CONNECT. DEVELOP.**\n\n"
                        f"{member.mention} vient de rejoindre le serveur !"
                    ),
                    color=0xFFFFFF,
                )
                await welcome_channel.send(embed=embed)
            except Exception as exc:
                log.error("Failed to send welcome message: %s", exc)

        # 2. Post verification message in │rules
        if rules_channel:
            try:
                rules_embed = create_embed(
                    title="📖 Règlement SKORM",
                    description=(
                        f"👋 **Bienvenue {member.mention} !**\n\n"
                        "Pour accéder au serveur, réagis avec ✅ ci-dessous "
                        "pour accepter le règlement."
                    ),
                    color=0xFFFFFF,
                )
                msg = await rules_channel.send(embed=rules_embed)
                await msg.add_reaction(VERIFY_EMOJI)
            except Exception as exc:
                log.error("Failed to post verification in │rules: %s", exc)

        # 3. Send DM with welcome + 2 tasks
        try:
            dm_embed = create_embed(
                title="🌩️ Bienvenue chez SKORM !",
                description=(
                    "**CREATE. CONNECT. DEVELOP.**\n\n"
                    "Tu viens de rejoindre le serveur officiel SKORM.\n\n"
                    "Pour accéder au serveur, complète ces 2 étapes :\n\n"
                    "1️⃣ **Accepte le règlement**\n"
                    f"   Va dans <#{rules_channel.id}> et réagis avec ✅\n"
                    if rules_channel else "   Va dans │rules et réagis avec ✅\n"
                    "2️⃣ **Choisis ton rôle**\n"
                    f"   Va dans <#{roles_channel.id}> et sélectionne ton parcours"
                    if roles_channel else "   Va dans │claim-your-roles et sélectionne ton parcours",
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

        # Fetch the message to verify it's a rules embed
        try:
            msg = await rules_channel.fetch_message(payload.message_id)
        except discord.NotFound:
            log.warning("Verification message %s not found", payload.message_id)
            return
        except Exception as exc:
            log.error("Failed to fetch message %s: %s", payload.message_id, exc)
            return

        # Check this is a verification embed (posted by bot with rules title)
        if msg.author != self.bot.user:
            return
        if not msg.embeds:
            return
        if "Règlement" not in msg.embeds[0].title:
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
            await msg.remove_reaction(payload.emoji, member)
        except Exception:
            pass

        # Send confirmation in DM
        roles_channel = get_channel_by_name(guild, ROLES_CHANNEL_NAME)
        try:
            confirm_embed = create_embed(
                title="✅ Règlement accepté !",
                description=(
                    "Tu es maintenant vérifié sur SKORM.\n\n"
                    "Il ne te reste plus qu'une étape :\n\n"
                    f"🎭 **Choisis ton rôle** dans <#{roles_channel.id}>"
                    if roles_channel else "🎭 Choisis ton rôle dans │claim-your-roles",
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