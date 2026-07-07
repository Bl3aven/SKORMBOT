"""
SKORMAgency - Logging cog
Logs moderation events, deleted/edited messages and role changes to mod-logs.
Also auto-secures new voice channels.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands

from bot.cogs.utils import create_embed, get_channel_by_name

log = logging.getLogger("skorm.logging")


MOD_LOGS_NAME = "│mod-logs"
AUDIT_LOGS_NAME = "│audit-logs"


class LoggingCog(commands.Cog):
    """Centralised moderation/action logging."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # --- Helpers ---
    async def _mod_logs(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        return get_channel_by_name(guild, MOD_LOGS_NAME)

    async def log_action(
        self,
        guild: discord.Guild,
        action: str,
        user: discord.abc.User,
        moderator: Optional[discord.abc.User] = None,
        reason: Optional[str] = None,
        channel: Optional[discord.abc.GuildChannel] = None,
        extra_fields: Optional[list] = None,
    ) -> None:
        """Generic logging entry."""
        target = await self._mod_logs(guild)
        if target is None:
            return
        fields = [
            ("Utilisateur", f"{user.mention} (`{user.id}`)", True),
        ]
        if moderator:
            fields.append(("Modérateur", f"{moderator.mention} (`{moderator.id}`)", True))
        if channel:
            fields.append(("Salon", channel.mention, True))
        if reason:
            fields.append(("Raison", reason[:1024], False))
        if extra_fields:
            fields.extend(extra_fields)
        embed = create_embed(
            title=f"📕 {action}",
            description=f"Action effectuée le {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}",
            fields=fields,
        )
        try:
            await target.send(embed=embed)
        except Exception as exc:
            log.error("log_action failed: %s", exc)

    # --- Events ---
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return
        target = await self._mod_logs(message.guild)
        if target is None:
            return
        # Skip logs from the logs channels themselves
        if message.channel.id == target.id:
            return
        content_preview = (message.content or "")[:1024] or "[embed/attachment]"
        embed = create_embed(
            title="🗑️ Message supprimé",
            description=(
                f"**Auteur** : {message.author.mention}\n"
                f"**Salon** : {message.channel.mention}"
            ),
            fields=[("Contenu", f"```{content_preview}```", False)],
        )
        try:
            await target.send(embed=embed)
        except Exception as exc:
            log.error("on_message_delete log failed: %s", exc)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot:
            return
        if before.guild is None:
            return
        if before.content == after.content:
            return
        target = await self._mod_logs(before.guild)
        if target is None:
            return
        if before.channel.id == target.id:
            return
        embed = create_embed(
            title="✏️ Message édité",
            description=(
                f"**Auteur** : {before.author.mention}\n"
                f"**Salon** : {before.channel.mention}\n"
                f"[Aller au message]({after.jump_url})"
            ),
            fields=[
                ("Avant", f"```{before.content[:1024] or '[embed]'}```", False),
                ("Après", f"```{after.content[:1024] or '[embed]'}```", False),
            ],
        )
        try:
            await target.send(embed=embed)
        except Exception as exc:
            log.error("on_message_edit log failed: %s", exc)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        await self.log_action(
            guild=guild,
            action="Utilisateur banni",
            user=user,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        # Try to distinguish kick via audit logs
        await self.log_action(
            guild=member.guild,
            action="Membre parti",
            user=member,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles == after.roles:
            return
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if not added and not removed:
            return
        await self.log_action(
            guild=after.guild,
            action="Rôles modifiés",
            user=after,
            extra_fields=[
                ("Rôles ajoutés", ", ".join(r.mention for r in added) or "—", False),
                ("Rôles retirés", ", ".join(r.mention for r in removed) or "—", False),
            ],
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self.log_action(
            guild=channel.guild,
            action="Salon créé",
            user=self.bot.user,
            channel=channel,
        )

        # Auto-secure new voice channels
        if isinstance(channel, discord.VoiceChannel):
            await self._secure_voice_channel(channel)

    async def _secure_voice_channel(self, channel: discord.VoiceChannel) -> None:
        """Apply restrictive permissions to a voice channel for user roles."""
        DENY_PERMS = [
            "manage_channels", "manage_webhooks",
            "deafen_members", "move_members", "priority_speaker",
            "mention_everyone", "manage_messages",
        ]

        guild = channel.guild
        from bot.cogs.utils import DIRECTION_ROLES, STAFF_ROLES
        ADMIN_ROLES = DIRECTION_ROLES | STAFF_ROLES

        def deny_overwrite():
            ow = discord.PermissionOverwrite()
            for perm in DENY_PERMS:
                setattr(ow, perm, False)
            return ow

        try:
            ow = {guild.default_role: deny_overwrite()}
            for role in guild.roles:
                if role.name in ADMIN_ROLES or role.is_default():
                    continue
                ow[role] = deny_overwrite()
            await channel.edit(overwrites=ow, reason="SKORM voice security (auto)")
        except Exception as exc:
            log.warning("Failed to auto-secure voice channel %s: %s", channel.name, exc)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.log_action(
            guild=channel.guild,
            action="Salon supprimé",
            user=self.bot.user,
            channel=channel,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingCog(bot))