"""
SKORMAgency - Moderation cog
Slash commands for warn, mute, kick, ban + auto-deletion of suspicious links.
"""
import asyncio
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

    # === /cleanchat command implementation (registered explicitly in setup) ===
    async def cleanchat_impl(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ AdminDiscord role required.", ephemeral=True)
            return
        has_role = any(r.name == "AdminDiscord" for r in interaction.user.roles)
        if not has_role:
            await interaction.response.send_message("❌ AdminDiscord role required.", ephemeral=True)
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ This command only works in text channels.", ephemeral=True)
            return

        view = CleanChatView(interaction.user.id)
        try:
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
                view=view,
            )
        except Exception:
            log.exception("Failed to send cleanchat confirmation message")
            try:
                await interaction.followup.send("❌ Unable to show confirmation UI.", ephemeral=True)
            except Exception:
                pass
            return

        # Wait for the user's confirmation via the view we created above.
        await view.wait()

        if not view.value:
            return

        status_msg = await interaction.channel.send("⏳ Cleaning channel…")
        deleted = 0
        errors = 0

        # Use bulk-delete for recent messages (faster) and individual deletes
        # for messages older than 14 days (not supported by bulk delete).
        now = discord.utils.utcnow()
        cutoff = now - timedelta(days=14)

        while True:
            # Fetch a batch of messages (most recent first)
            batch = [m async for m in channel.history(limit=100, oldest_first=False)]
            if not batch:
                break

            # Remove our status message from the batch if present
            batch = [m for m in batch if m.id != status_msg.id]
            if not batch:
                break

            # Unpin any pinned messages so they become deletable
            for m in list(batch):
                if getattr(m, "pinned", False):
                    try:
                        await m.unpin()
                    except Exception:
                        pass

            recent = [m for m in batch if m.created_at and m.created_at > cutoff]
            old = [m for m in batch if m not in recent]

            # Bulk delete recent messages (up to 100)
            if recent:
                try:
                    await channel.delete_messages(recent)
                    deleted += len(recent)
                except Exception:
                    # Fallback to individual deletion on any failure
                    for m in recent:
                        try:
                            await m.delete()
                            deleted += 1
                        except Exception:
                            errors += 1
                            await asyncio.sleep(1)

            # Individually delete older messages
            for m in old:
                try:
                    await m.delete()
                    deleted += 1
                    if deleted % 100 == 0:
                        await status_msg.edit(content=f"⏳ Cleaning channel… ({deleted} deleted)")
                        await asyncio.sleep(1)
                except discord.Forbidden:
                    errors += 1
                except discord.HTTPException:
                    errors += 1
                    await asyncio.sleep(2)

            # Update status and continue until channel empty
            try:
                await status_msg.edit(content=f"⏳ Cleaning channel… ({deleted} deleted)")
            except Exception:
                pass
            await asyncio.sleep(0.6)

        await status_msg.edit(content=(
            f"✅ **Channel cleaned!**\n\n"
            f"Deleted: {deleted} messages\n"
            f"Errors: {errors}\n\n"
            f"Requested by {interaction.user.mention}"
        ))

        await asyncio.sleep(5)
        try:
            await status_msg.delete()
        except discord.Forbidden:
            pass


# === Clean Chat View (must be outside cog for button callbacks) ===
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


async def setup(bot: commands.Bot) -> None:
    cog = ModerationCog(bot)
    await bot.add_cog(cog)

    # Ensure a root /cleanchat command is registered (bound to the cog instance).
    async def _cleanchat(interaction: discord.Interaction) -> None:
        await cog.cleanchat_impl(interaction)

    cmd = app_commands.Command(
        name="cleanchat",
        description="Cleans all message history in the current channel.",
        callback=_cleanchat,
    )
    try:
        bot.tree.add_command(cmd)
    except Exception as e:
        log.warning(f"Failed to add root cleanchat command: {e}")