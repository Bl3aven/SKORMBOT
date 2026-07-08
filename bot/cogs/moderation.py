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
                        title="🔗 Suspicious link deleted",
                        description=(
                            f"{message.author.mention}, URL shorteners are "
                            "not allowed on this server."
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
                    action="Suspicious link deleted",
                    user=message.author,
                    channel=message.channel,
                    reason=message.content[:256] or None,
                )

    # --- Slash commands ---
    mod_group = app_commands.Group(
        name="mod",
        description="Moderation commands.",
    )

    @mod_group.command(name="warn", description="Warns a member.")
    @app_commands.describe(user="Member to warn", reason="Reason")
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_warn(interaction.user):
            await interaction.response.send_message(
                "❌ Staff only.", ephemeral=True
            )
            return
        if user.bot:
            await interaction.response.send_message(
                "❌ Can't warn a bot.", ephemeral=True
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
            title=f"⚠️ Warning #{warn_id}",
            description=(
                f"**Member** : {user.mention}\n"
                f"**Reason** : {reason}\n"
                f"**Total** : {count} warning(s)"
                + ("\n**⏱️ 10-minute auto timeout applied.**" if auto_muted else "")
            ),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        # DM the user
        try:
            warning_msg = "A 10-minute timeout has just been applied." if auto_muted else "After 3 warnings, a timeout is applied."
            await user.send(embed=create_embed(
                title=f"⚠️ You received a warning on {interaction.guild.name}",
                description=(
                    f"**Reason** : {reason}\n"
                    f"You now have **{count}** warning(s).\n"
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
                action="Warning",
                user=user,
                moderator=interaction.user,
                reason=reason,
                extra_fields=[("Total", f"{count}", True)],
            )

    @mod_group.command(name="mute", description="Puts a member in timeout.")
    @app_commands.describe(
        user="Member to mute",
        duration="Duration (e.g., 10m, 1h, 2h)",
        reason="Reason",
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
                "❌ Staff only.", ephemeral=True
            )
            return
        seconds = parse_duration(duration)
        if seconds is None or seconds < 60 or seconds > 86400:
            await interaction.response.send_message(
                "❌ Invalid duration (between 1 min and 24h).", ephemeral=True
            )
            return

        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await user.timeout(until, reason=f"Mute: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Insufficient permissions to mute this member.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=create_embed(
                title="🔇 Member muted",
                description=(
                    f"**Member** : {user.mention}\n"
                    f"**Duration** : {format_duration(seconds)}\n"
                    f"**Reason** : {reason}"
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
                extra_fields=[("Duration", format_duration(seconds), True)],
            )

    @mod_group.command(name="unmute", description="Removes timeout from a member.")
    @app_commands.describe(user="Member to unmute")
    async def unmute(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_warn(interaction.user):
            await interaction.response.send_message(
                "❌ Staff only.", ephemeral=True
            )
            return
        try:
            await user.timeout(None, reason="Unmute")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Insufficient permissions.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=create_embed(
                title="🔊 Member unmuted",
                description=f"{user.mention} can speak again.",
            )
        )
        logging_cog = interaction.client.get_cog("LoggingCog")
        if logging_cog:
            await logging_cog.log_action(
                guild=interaction.guild,
                action="Timeout removed",
                user=user,
                moderator=interaction.user,
            )

    @mod_group.command(name="kick", description="Kicks a member.")
    @app_commands.describe(user="Member to kick", reason="Reason")
    async def kick(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "Not specified",
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_kick_ban(interaction.user):
            await interaction.response.send_message(
                "❌ Management only.", ephemeral=True
            )
            return
        try:
            await user.kick(reason=f"Kick: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Insufficient permissions.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=create_embed(
                title="👢 Member kicked",
                description=f"**Member** : {user.mention}\n**Reason** : {reason}",
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

    @mod_group.command(name="ban", description="Bans a member.")
    @app_commands.describe(user="Member to ban", reason="Reason")
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "Not specified",
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_kick_ban(interaction.user):
            await interaction.response.send_message(
                "❌ Management only.", ephemeral=True
            )
            return
        try:
            await user.ban(reason=f"Ban: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Insufficient permissions.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=create_embed(
                title="⛔ Member banned",
                description=f"**Member** : {user.mention}\n**Reason** : {reason}",
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

    @mod_group.command(name="warnings", description="Shows a member's warnings.")
    @app_commands.describe(user="Target member")
    async def warnings(
        self, interaction: discord.Interaction, user: discord.Member
    ) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._user_can_warn(interaction.user):
            await interaction.response.send_message(
                "❌ Staff only.", ephemeral=True
            )
            return
        rows = await db.list_warnings(user.id)
        if not rows:
            await interaction.response.send_message(
                embed=create_embed(
                    title=f"⚠️ Warnings for {user.display_name}",
                    description="No warnings.",
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


# === Clean Chat View ===
class CleanChatView(discord.ui.View):
    """Confirmation view for /cleanchat."""

    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=30)
        self.user_id = user_id
        self.value = False

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Not your confirmation.", ephemeral=True)
            return
        self.value = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Not your confirmation.", ephemeral=True)
            return
        self.value = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ Cancelled.", view=self)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# === Standalone slash command (not in group) ===
@app_commands.command(name="cleanchat", description="Cleans all message history in the current channel.")
async def cleanchat(interaction: discord.Interaction) -> None:
    # AdminDiscord role only
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return
    has_role = any(r.name == "Admin" for r in interaction.user.roles)
    if not has_role:
        await interaction.response.send_message("❌ AdminDiscord role required.", ephemeral=True)
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("❌ This command only works in text channels.", ephemeral=True)
        return

    await interaction.response.send_message(
        embed=create_embed(
            title="🧹 Clean Chat",
            description=(
                f"This will delete **all messages** in {channel.mention}.\n\n"
                "This action is **irreversible**.\n\n"
                "Confirm below to proceed."
            ),
            color=0xFF0000,
        ),
        view=CleanChatView(interaction.user.id),
    )

    # Wait for confirmation
    view: CleanChatView = interaction.response.message.view
    await view.wait()

    if not view.value:
        return

    # Start cleaning
    status_msg = await interaction.channel.send("⏳ Cleaning channel…")
    deleted = 0
    errors = 0

    async for msg in channel.history(limit=None, oldest_first=False):
        if msg.id == status_msg.id:
            continue
        if msg.system:
            continue
        try:
            await msg.delete()
            deleted += 1
            if deleted % 100 == 0:
                await status_msg.edit(content=f"⏳ Cleaning channel… ({deleted} deleted)")
                await asyncio.sleep(1)
        except discord.Forbidden:
            errors += 1
        except discord.HTTPException:
            errors += 1
            await asyncio.sleep(2)

    await status_msg.edit(content=(
        f"✅ **Channel cleaned!**\n\n"
        f"Deleted: {deleted} messages\n"
        f"Errors: {errors}\n\n"
        f"Requested by {interaction.user.mention}"
    ))

    # Delete the confirmation message after 5s
    await asyncio.sleep(5)
    try:
        await status_msg.delete()
    except discord.Forbidden:
        pass


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(cleanchat)
    await bot.add_cog(ModerationCog(bot))