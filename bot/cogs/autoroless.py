"""
SKORMAgency - Auto-roles cog
Manages the role-selection message in the 🎭・roles channel via reactions.
"""
import asyncio
import logging

import discord
from discord.ext import commands

from bot.cogs.utils import create_embed, get_channel_by_name, get_role_by_name

log = logging.getLogger("skorm.autoroles")


ROLES_CHANNEL_NAME = "│claim-your-roles"
SENTINEL_MESSAGE_TITLE = "🎭 Choose Your Roles"


# Maps an emoji to the role name that should be toggled
ROLE_EMOJI_MAP = {
    "🎤": "Artist",
    "🤝": "Agent",
    "🎓": "Student",
}


class AutoRolesCog(commands.Cog):
    """Auto-roles via reactions."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._initialised = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._initialised:
            return
        self._initialised = True
        await asyncio.sleep(2)
        try:
            await self._send_roles_message()
        except Exception as exc:
            log.error("Auto-roles init failed: %s", exc)

    async def _send_roles_message(self) -> None:
        """Post (or refresh) the role-selection embed in claim your role."""
        for guild in self.bot.guilds:
            channel = get_channel_by_name(guild, ROLES_CHANNEL_NAME)
            if channel is None:
                continue

            # Try to update an existing SKORM roles message instead of duplicating
            existing_message = None
            async for message in channel.history(limit=50):
                if (
                    message.author == self.bot.user
                    and message.embeds
                    and message.embeds[0].title == SENTINEL_MESSAGE_TITLE
                ):
                    existing_message = message
                    break

            description_lines = [
                "**React below to get your roles.**",
                "You can remove a reaction to remove a role.",
                "",
                "🎤 — Artist",
                "🤝 — Agent",
                "🎓 — Student",
            ]
            embed = create_embed(
                title=SENTINEL_MESSAGE_TITLE,
                description="\n".join(description_lines),
            )

            if existing_message is not None:
                try:
                    await existing_message.edit(embed=embed)
                    await self._add_reactions(existing_message)
                    continue
                except Exception as exc:
                    log.warning("Failed to edit roles message: %s", exc)

            try:
                message = await channel.send(embed=embed)
                await self._add_reactions(message)
            except Exception as exc:
                log.error("Failed to send roles message: %s", exc)

    @staticmethod
    async def _add_reactions(message: discord.Message) -> None:
        emojis = list(ROLE_EMOJI_MAP.keys())
        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except Exception:
                pass

    @staticmethod
    async def _toggle_role(
        member: discord.Member, emoji: str, add: bool
    ) -> bool:
        """Add or remove the role mapped to `emoji`. Return True on success."""
        role_name = ROLE_EMOJI_MAP.get(emoji)
        if not role_name:
            return False
        role = get_role_by_name(member.guild, role_name)
        if role is None:
            return False
        try:
            if add:
                if role not in member.roles:
                    await member.add_roles(role, reason="Auto-role reaction")
            else:
                if role in member.roles:
                    await member.remove_roles(role, reason="Auto-role reaction")
            return True
        except discord.Forbidden:
            return False
        except Exception as exc:
            log.error("Role toggle failed for %s/%s: %s", member, role_name, exc)
            return False

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Message, reaction_member) -> None:  # noqa: ANN001
        if reaction_member.bot:
            return
        if reaction.message.author != self.bot.user:
            return
        if reaction.message.embeds and reaction.message.embeds[0].title != SENTINEL_MESSAGE_TITLE:
            return
        emoji = str(reaction.emoji)
        if emoji not in ROLE_EMOJI_MAP:
            return
        await self._toggle_role(reaction_member, emoji, add=True)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Message, reaction_member) -> None:  # noqa: ANN001
        if reaction_member.bot:
            return
        if reaction.message.author != self.bot.user:
            return
        if reaction.message.embeds and reaction.message.embeds[0].title != SENTINEL_MESSAGE_TITLE:
            return
        emoji = str(reaction.emoji)
        if emoji not in ROLE_EMOJI_MAP:
            return
        await self._toggle_role(reaction_member, emoji, add=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoRolesCog(bot))