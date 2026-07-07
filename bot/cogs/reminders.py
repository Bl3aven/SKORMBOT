"""
SKORMAgency - Reminders cog
Slash commands for personal reminders and Discord events.
"""
import asyncio
import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.cogs import db
from bot.cogs.utils import create_embed, get_channel_by_name, parse_duration, format_duration

log = logging.getLogger("skorm.reminders")


EVENTS_CHANNEL_NAME = "│events"


remind_group = app_commands.Group(
    name="remind",
    description="Gestion des rappels personnels.",
)
event_group = app_commands.Group(
    name="event",
    description="Gestion des événements du serveur.",
)


@remind_group.command(name="set", description="Programme un rappel.")
@app_commands.describe(
    message="Texte du rappel",
    duration="Durée (ex: 30m, 2h, 1d, 2 days)",
)
async def remind_set(
    interaction: discord.Interaction,
    message: str,
    duration: str,
) -> None:
    seconds = parse_duration(duration)
    if seconds is None or seconds <= 0:
        await interaction.response.send_message(
            "❌ Format de durée invalide. Exemples : `30m`, `2h`, `1d`, `2 hours`.",
            ephemeral=True,
        )
        return
    if seconds > 60 * 60 * 24 * 365:
        await interaction.response.send_message(
            "❌ Durée maximale : 1 an.", ephemeral=True
        )
        return

    remind_at = datetime.utcnow() + timedelta(seconds=seconds)
    reminder_id = await db.add_reminder(interaction.user.id, message, remind_at)

    embed = create_embed(
        title="⏰ Rappel programmé",
        description=(
            f"**ID** : `{reminder_id}`\n"
            f"**Dans** : {format_duration(seconds)}\n"
            f"**Rappel** : {message}"
        ),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@remind_group.command(name="list", description="Liste tes rappels actifs.")
async def remind_list(interaction: discord.Interaction) -> None:
    rows = await db.list_active_reminders(interaction.user.id)
    if not rows:
        await interaction.response.send_message(
            "Aucun rappel actif.", ephemeral=True
        )
        return
    lines = []
    for r in rows:
        remind_at = datetime.fromisoformat(r["remind_at"])
        delta = remind_at - datetime.utcnow()
        lines.append(
            f"`#{r['id']}` — {r['message']} — "
            f"dans {format_duration(int(delta.total_seconds()))}"
        )
    await interaction.response.send_message(
        embed=create_embed(
            title="⏰ Tes rappels actifs",
            description="\n".join(lines)[:2000],
        ),
        ephemeral=True,
    )


@remind_group.command(name="delete", description="Supprime un rappel actif.")
@app_commands.describe(reminder_id="ID du rappel à supprimer")
async def remind_delete(
    interaction: discord.Interaction,
    reminder_id: int,
) -> None:
    deleted = await db.delete_reminder(reminder_id, interaction.user.id)
    if deleted:
        await interaction.response.send_message(
            f"✅ Rappel `{reminder_id}` supprimé.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ Rappel `{reminder_id}` introuvable.", ephemeral=True
        )


@event_group.command(name="create", description="Crée un événement Discord.")
@app_commands.describe(
    name="Nom de l'événement",
    date="Date au format YYYY-MM-DD HH:MM (UTC)",
)
async def event_create(
    interaction: discord.Interaction,
    name: str,
    date: str,
) -> None:
    # Accept ISO-like format "YYYY-MM-DD HH:MM"
    try:
        event_time = datetime.strptime(date, "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            event_time = datetime.fromisoformat(date)
        except ValueError:
            await interaction.response.send_message(
                "❌ Format de date invalide. Utilise `YYYY-MM-DD HH:MM` (UTC).",
                ephemeral=True,
            )
            return

    if event_time < datetime.utcnow():
        await interaction.response.send_message(
            "❌ La date doit être dans le futur.", ephemeral=True
        )
        return

    event_id = await db.add_event(name, event_time)

    # Create a Discord scheduled event for the guild
    try:
        scheduled_time = discord.utils.utcnow() + (
            event_time - datetime.utcnow()
        )
        await interaction.guild.create_scheduled_event(
            name=name,
            start_time=scheduled_time,
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only,
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        log.warning("Could not create Discord scheduled event: %s", exc)

    embed = create_embed(
        title=f"📅 Événement créé — #{event_id}",
        description=(
            f"**Nom** : {name}\n"
            f"**Date** : {event_time.strftime('%d/%m/%Y %H:%M UTC')}\n"
            f"Notifications automatiques H-24 et H-1."
        ),
    )
    await interaction.response.send_message(embed=embed)


class RemindersCog(commands.Cog):
    """Background reminder scheduler and Discord events."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler.start()

    def cog_unload(self) -> None:
        self.scheduler.cancel()

    @tasks.loop(seconds=60)
    async def scheduler(self) -> None:
        await self._check_reminders()
        await self._check_events()

    @scheduler.before_loop
    async def before_scheduler(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_reminders(self) -> None:
        try:
            due = await db.get_due_reminders()
        except Exception as exc:
            log.error("Failed to fetch reminders: %s", exc)
            return
        for row in due:
            try:
                user = self.bot.get_user(row["user_id"])
                embed = create_embed(
                    title="⏰ Rappel",
                    description=row["message"],
                )
                if user is None:
                    continue
                try:
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass
            except Exception as exc:
                log.error("Reminder delivery failed: %s", exc)
            finally:
                await db.mark_reminder_done(row["id"])

    async def _check_events(self) -> None:
        try:
            events = await db.get_upcoming_events()
        except Exception as exc:
            log.error("Failed to fetch events: %s", exc)
            return
        for event in events:
            event_time = datetime.fromisoformat(event["event_time"])
            now = datetime.utcnow()
            delta = event_time - now
            seconds_left = delta.total_seconds()

            # H-24 notification
            if 0 < seconds_left <= 86400 and not event["notified_24h"]:
                await self._notify_event(event, "24h")
                await db.mark_event_notified(event["id"], "24h")
            # H-1 notification
            if 0 < seconds_left <= 3600 and not event["notified_1h"]:
                await self._notify_event(event, "1h")
                await db.mark_event_notified(event["id"], "1h")

    async def _notify_event(self, event, kind: str) -> None:
        # Send notification in every guild that has an events channel
        for guild in self.bot.guilds:
            channel = get_channel_by_name(guild, EVENTS_CHANNEL_NAME)
            if channel is None:
                continue
            embed = create_embed(
                title=f"📅 Rappel événement — {kind}",
                description=(
                    f"**{event['name']}**\n"
                    f"Démarre dans {kind} !\n"
                    f"Heure : {datetime.fromisoformat(event['event_time']).strftime('%d/%m/%Y %H:%M UTC')}"
                ),
            )
            try:
                await channel.send(embed=embed)
            except Exception as exc:
                log.error("Event notify failed: %s", exc)


async def setup(bot: commands.Bot) -> None:
    cog = RemindersCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(remind_group)
    bot.tree.add_command(event_group)