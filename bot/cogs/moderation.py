"""
SKORMAgency - Moderation cog
Slash commands for warn, mute, kick, ban + auto-deletion of suspicious links.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs import db
from bot.cogs.logging_cog import LoggingCog
from bot.cogs.utils import (
    create_embed,
    format_duration,
    parse_duration,
    check_admin_role,
    check_staff_role,
)

log = logging.getLogger("skorm.moderation")


# === Tunables ===
MAX_WARNINGS_BEFORE_MUTE = 3
AUTO_MUTE_DURATION = 600  # 10 minutes


SUSPICIOUS_DOMAINS = (
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "is.gd",
    "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy",
)


class ModerationCog(commands.Cog):
    """Staff and direction moderation tools."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._suspicious_re = re.compile(
            r"https?://(?:[\w-]+\.)*("
            + "|".join(re.escape(d) for d in SUSPICIOUS_DOMAINS)
            + r")(?:[/\?\=&\.\#\w-]*)?",
            re.IGNORECASE,
        )

    # --- Permission checks ---
    def _user_can_warn(self, member: discord.Member) -> bool:
        return check_staff_role(member)

    def _user_can_kick_ban(self, member: discord.Member) -> bool:
        return check_admin_role(member)

    # --- Events ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        # Staff can post anything
        if check_staff_role(message.author):
            return
        if self._suspicious_re.search(message.content or ""):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            try:
                await message.channel.send(
                    embed=create_embed(
                        title="🔗 Lien suspect supprimé",
                        description=(
                            f"{message.author.mention}, les raccourcisseurs de "
                            "liens ne sont pas autorisés sur ce serveur."
                        ),
                    ),
                    delete_after=8.0,
                )
            except Exception:
                pass
            # Log
            logging_cog = self.bot.get_cog("LoggingCog")
            if logging_cog:
                await logging_cog.log_action(
                    guild=message.guild,
                    action="Lien suspect supprimé",
                    user=message.author,
                    channel=message.channel,
                    reason=message.content[:256] or None,
                )

    # --- Slash commands ---
    mod_group = app_commands.Group(
        name="mod",
        description="Commandes de modération.",
    )

    @mod_group.command(name="warn", description="Avertit un membre.")
    @app_commands.describe(user="Membre à avertir", reason="Raison")
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_warn(interaction.user):
            await interaction.response.send_message(
                "❌ Réservé au staff.", ephemeral=True
            )
            return
        if user.bot:
            await interaction.response.send_message(
                "❌ Impossible d'avertir un bot.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        warn_id = await db.add_warning(user.id, reason, interaction.user.id)
        count = await db.count_warnings(user.id)

        # Auto-mute at threshold
        auto_muted = False
        if count >= MAX_WARNINGS_BEFORE_MUTE:
            try:
                until = discord.utils.utcnow() + timedelta(seconds=AUTO_MUTE_DURATION)
                await user.timeout(until, reason=f"Auto-mute after {count} warnings")
                auto_muted = True
            except discord.Forbidden:
                pass

        embed = create_embed(
            title=f"⚠️ Avertissement #{warn_id}",
            description=(
                f"**Membre** : {user.mention}\n"
                f"**Raison** : {reason}\n"
                f"**Total** : {count} avertissement(s)"
                + ("\n**⏱️ Timeout automatique de 10 min appliqué.**" if auto_muted else "")
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # DM the user
        try:
            warning_msg = "Un timeout de 10 minutes vient d'être appliqué." if auto_muted else "À partir de 3 avertissements, un timeout est appliqué."
            await user.send(embed=create_embed(
                title=f"⚠️ Tu as reçu un avertissement sur {interaction.guild.name}",
                description=(
                    f"**Raison** : {reason}\n"
                    f"Tu as maintenant **{count}** avertissement(s).\n"
                    f"{warning_msg}"
                ),
            ))
        except discord.Forbidden:
            pass

        # Log
        logging_cog = interaction.client.get_cog("LoggingCog")
        if logging_cog:
            await logging_cog.log_action(
                guild=interaction.guild,
                action="Avertissement",
                user=user,
                moderator=interaction.user,
                reason=reason,
                extra_fields=[("Total", f"{count}", True)],
            )

    @mod_group.command(name="mute", description="Met un membre en timeout.")
    @app_commands.describe(
        user="Membre à mute",
        duration="Durée (ex: 10m, 1h, 2h)",
        reason="Raison",
    )
    async def mute(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration: str,
        reason: str = "Non précisée",
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_warn(interaction.user):
            await interaction.response.send_message(
                "❌ Réservé au staff.", ephemeral=True
            )
            return
        seconds = parse_duration(duration)
        if seconds is None or seconds < 60 or seconds > 86400:
            await interaction.response.send_message(
                "❌ Durée invalide (entre 1 min et 24h).", ephemeral=True
            )
            return

        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await user.timeout(until, reason=f"Mute: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Permissions insuffisantes pour mute ce membre.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=create_embed(
                title="🔇 Membre mute",
                description=(
                    f"**Membre** : {user.mention}\n"
                    f"**Durée** : {format_duration(seconds)}\n"
                    f"**Raison** : {reason}"
                ),
            )
        )

        logging_cog = interaction.client.get_cog("LoggingCog")
        if logging_cog:
            await logging_cog.log_action(
                guild=interaction.guild,
                action="Timeout",
                user=user,
                moderator=interaction.user,
                reason=reason,
                extra_fields=[("Durée", format_duration(seconds), True)],
            )

    @mod_group.command(name="unmute", description="Retire le timeout d'un membre.")
    @app_commands.describe(user="Membre à unmute")
    async def unmute(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_warn(interaction.user):
            await interaction.response.send_message(
                "❌ Réservé au staff.", ephemeral=True
            )
            return
        try:
            await user.timeout(None, reason="Unmute")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Permissions insuffisantes.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=create_embed(
                title="🔊 Membre unmute",
                description=f"{user.mention} peut à nouveau parler.",
            )
        )
        logging_cog = interaction.client.get_cog("LoggingCog")
        if logging_cog:
            await logging_cog.log_action(
                guild=interaction.guild,
                action="Timeout retiré",
                user=user,
                moderator=interaction.user,
            )

    @mod_group.command(name="kick", description="Exclut un membre.")
    @app_commands.describe(user="Membre à exclure", reason="Raison")
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "Non précisée",
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_kick_ban(interaction.user):
            await interaction.response.send_message(
                "❌ Réservé à la Direction.", ephemeral=True
            )
            return
        try:
            await user.kick(reason=f"Kick: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Permissions insuffisantes.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=create_embed(
                title="👢 Membre exclu",
                description=f"**Membre** : {user.mention}\n**Raison** : {reason}",
            )
        )
        logging_cog = interaction.client.get_cog("LoggingCog")
        if logging_cog:
            await logging_cog.log_action(
                guild=interaction.guild,
                action="Kick",
                user=user,
                moderator=interaction.user,
                reason=reason,
            )

    @mod_group.command(name="ban", description="Bannit un membre.")
    @app_commands.describe(user="Membre à bannir", reason="Raison")
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "Non précisée",
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_kick_ban(interaction.user):
            await interaction.response.send_message(
                "❌ Réservé à la Direction.", ephemeral=True
            )
            return
        try:
            await user.ban(reason=f"Ban: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Permissions insuffisantes.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=create_embed(
                title="⛔ Membre banni",
                description=f"**Membre** : {user.mention}\n**Raison** : {reason}",
            )
        )
        logging_cog = interaction.client.get_cog("LoggingCog")
        if logging_cog:
            await logging_cog.log_action(
                guild=interaction.guild,
                action="Ban",
                user=user,
                moderator=interaction.user,
                reason=reason,
            )

    @mod_group.command(name="warnings", description="Affiche les avertissements d'un membre.")
    @app_commands.describe(user="Membre ciblé")
    async def warnings(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_warn(interaction.user):
            await interaction.response.send_message(
                "❌ Réservé au staff.", ephemeral=True
            )
            return
        rows = await db.get_warnings(user.id)
        if not rows:
            await interaction.response.send_message(
                embed=create_embed(
                    title=f"⚠️ Avertissements de {user.display_name}",
                    description="Aucun avertissement.",
                ),
                ephemeral=True,
            )
            return
        lines = []
        for r in rows[:25]:
            ts = r["timestamp"].replace("T", " ")[:19]
            lines.append(
                f"`#{r['id']}` — {ts} — par <@{r['moderator_id']}> — {r['reason']}"
            )
        await interaction.response.send_message(
            embed=create_embed(
                title=f"⚠️ Avertissements de {user.display_name} ({len(rows)})",
                description="\n".join(lines)[:2000],
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))