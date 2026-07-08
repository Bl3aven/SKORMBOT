"""
SKORMAgency - Tickets cog
Creates, claims, transfers and closes support tickets.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs import db
from bot.cogs.utils import (
    create_embed,
    get_channel_by_name,
    check_staff_role,
)

log = logging.getLogger("skorm.tickets")


SUPPORT_CHANNEL_NAME = "│support"
LOGS_CHANNEL_NAME = "│mod-logs"
TICKETS_CATEGORY_ID = 1523995159665053746
OPEN_TICKET_TITLE = "🎫 Support SKORM"


# === Views ===
class OpenTicketView(discord.ui.View):
    """Persistent view with the open-ticket button."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎫 Open a Ticket",
        style=discord.ButtonStyle.secondary,
        custom_id="skorm:open-ticket",
    )
    async def open_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        cog: Optional[TicketsCog] = interaction.client.get_cog("TicketsCog")
        if cog is None:
            await interaction.followup.send(
                "❌ Ticket system unavailable.", ephemeral=True
            )
            return
        await cog._create_ticket_for(interaction)


class TicketControlsView(discord.ui.View):
    """Controls inside an open ticket."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 Claim",
        style=discord.ButtonStyle.secondary,
        custom_id="skorm:ticket-claim",
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member) or not check_staff_role(member):
            await interaction.followup.send(
                "❌ Staff only.", ephemeral=True
            )
            return
        cog: Optional[TicketsCog] = interaction.client.get_cog("TicketsCog")
        if cog is None:
            return
        ticket = await db.get_ticket_by_channel(interaction.channel.id)
        if ticket is None:
            await interaction.followup.send(
                "❌ Ticket not found.", ephemeral=True
            )
            return
        await db.claim_ticket(ticket["id"], member.id)
        await interaction.channel.send(
            embed=create_embed(
                title="✅ Ticket claimed",
                description=f"This ticket is now being handled by {member.mention}.",
            )
        )
        await interaction.followup.send(
            "Claim recorded.", ephemeral=True
        )

    @discord.ui.button(
        label="❌ Fermer",
        style=discord.ButtonStyle.danger,
        custom_id="skorm:ticket-close",
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        if not isinstance(member, discord.Member) or not check_staff_role(member):
            await interaction.followup.send(
                "❌ Staff only.", ephemeral=True
            )
            return
        cog: Optional[TicketsCog] = interaction.client.get_cog("TicketsCog")
        if cog is None:
            return
        await cog._close_ticket_channel(interaction.channel)


# === Slash commands ===
ticket_group = app_commands.Group(
    name="ticket",
    description="Support ticket management.",
)


@ticket_group.command(name="close", description="Closes the current ticket.")
async def ticket_close(interaction: discord.Interaction) -> None:
    if not isinstance(interaction.user, discord.Member) or not check_staff_role(interaction.user):
        await interaction.response.send_message(
            "❌ Staff only.", ephemeral=True
        )
        return
    cog: Optional[TicketsCog] = interaction.client.get_cog("TicketsCog")
    if cog is None:
        return
    await interaction.response.defer(ephemeral=True)
    await cog._close_ticket_channel(interaction.channel)


@ticket_group.command(name="claim", description="Takes ownership of the ticket.")
async def ticket_claim(interaction: discord.Interaction) -> None:
    if not isinstance(interaction.user, discord.Member) or not check_staff_role(interaction.user):
        await interaction.response.send_message(
            "❌ Staff only.", ephemeral=True
        )
        return
    cog: Optional[TicketsCog] = interaction.client.get_cog("TicketsCog")
    if cog is None:
        return
    ticket = await db.get_ticket_by_channel(interaction.channel.id)
    if ticket is None:
        await interaction.response.send_message(
            "❌ Ticket not found.", ephemeral=True
        )
        return
    await db.claim_ticket(ticket["id"], interaction.user.id)
    await interaction.response.send_message(
        f"✅ Ticket claimed by {interaction.user.mention}.",
    )


@ticket_group.command(name="transfer", description="Adds a user to the ticket.")
@app_commands.describe(user="User to add to the ticket")
async def ticket_transfer(
    interaction: discord.Interaction, user: discord.Member
) -> None:
    if not isinstance(interaction.user, discord.Member) or not check_staff_role(interaction.user):
        await interaction.response.send_message(
            "❌ Staff only.", ephemeral=True
        )
        return
    await interaction.channel.set_permissions(
        user, view_channel=True, send_messages=True, read_message_history=True,
    )
    await interaction.response.send_message(
        f"✅ {user.mention} added to the ticket."
    )


# === Cog ===
class TicketsCog(commands.Cog):
    """Ticket system."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._initialised = False

    async def cog_load(self) -> None:
        self.bot.add_view(OpenTicketView())
        self.bot.add_view(TicketControlsView())

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._initialised:
            return
        self._initialised = True
        await asyncio.sleep(2)
        try:
            await self._post_open_ticket_message()
        except Exception as exc:
            log.error("Tickets init failed: %s", exc)

    async def _post_open_ticket_message(self) -> None:
        for guild in self.bot.guilds:
            channel = get_channel_by_name(guild, SUPPORT_CHANNEL_NAME)
            if channel is None:
                continue

            async for message in channel.history(limit=20):
                if (
                    message.author == self.bot.user
                    and message.embeds
                    and message.embeds[0].title == OPEN_TICKET_TITLE
                ):
                    return

            embed = create_embed(
                title=OPEN_TICKET_TITLE,
                description=(
                    "**Need help?**\n\n"
                    "Click the button below to open a private ticket with "
                    "staff. Our team will get back to you as soon as possible."
                ),
            )
            try:
                await channel.send(embed=embed, view=OpenTicketView())
            except Exception as exc:
                log.error("Failed to post open-ticket message: %s", exc)

    async def _get_ticket_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        category = guild.get_channel(TICKETS_CATEGORY_ID)
        if isinstance(category, discord.CategoryChannel):
            return category
        log.warning("Tickets category %s not found in %s", TICKETS_CATEGORY_ID, guild.name)
        return None

    def _build_overwrites(
        self, guild: discord.Guild, member: discord.Member
    ) -> dict:
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        # Author can see + write
        ow[member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
        # Bot
        if guild.me:
            ow[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )
        # Staff roles
        from bot.cogs.utils import STAFF_ROLES, DIRECTION_ROLES
        for role_name in list(STAFF_ROLES) + list(DIRECTION_ROLES):
            role = next((r for r in guild.roles if r.name == role_name), None)
            if role:
                ow[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
        return ow

    async def _create_ticket_for(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.followup.send(
                "❌ Action unavailable.", ephemeral=True
            )
            return

        category = await self._get_ticket_category(guild)
        if category is None:
            await interaction.followup.send(
                "❌ Tickets category not found.", ephemeral=True
            )
            return

        # Sanitise username for channel name
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "-" for c in member.display_name
        )[:32].strip("-") or member.name

        # Try a few suffixes if needed
        channel = None
        for attempt in range(5):
            suffix = f"{attempt:02d}" if attempt else ""
            base_name = f"🎫-{safe_name}{suffix}".lower()
            try:
                channel = await guild.create_text_channel(
                    name=base_name,
                    category=category,
                    overwrites=self._build_overwrites(guild, member),
                    reason=f"Ticket ouvert par {member}",
                )
                break
            except discord.HTTPException:
                continue
        if channel is None:
            await interaction.followup.send(
                "❌ Could not create ticket channel.", ephemeral=True
            )
            return

        ticket_id = await db.create_ticket(member.id, channel.id)
        embed = create_embed(
            title=f"Ticket #{ticket_id}",
            description=(
                f"Welcome {member.mention}, a staff member will respond "
                "shortly.\n\n"
                "Please describe your request in detail."
            ),
            fields=[
                ("Status", "🟢 Open", True),
                ("Created on", datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"), True),
            ],
        )
        await channel.send(embed=embed, view=TicketControlsView())
        await interaction.followup.send(
            f"✅ Ticket created: {channel.mention}", ephemeral=True
        )

    async def _close_ticket_channel(self, channel: discord.TextChannel) -> None:
        ticket = await db.get_ticket_by_channel(channel.id)
        if ticket is None:
            await channel.send("⚠️ No ticket associated with this channel.")
            return

        # Build transcript
        transcript_lines = [
            f"# Transcript #{ticket['id']} — {channel.name}",
            f"Creator: {ticket['creator_id']}",
            f"Created: {ticket['created_at']}",
            "",
        ]
        try:
            async for message in channel.history(limit=200, oldest_first=True):
                ts = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                author = f"{message.author} ({message.author.id})"
                content = message.content or "[embed/attachment]"
                transcript_lines.append(f"[{ts}] {author}: {content}")
        except Exception:
            pass
        transcript = "\n".join(transcript_lines)

        # Log to mod-logs
        log_channel = get_channel_by_name(channel.guild, LOGS_CHANNEL_NAME)
        if log_channel:
            try:
                file = discord.File(
                    fp=__import__("io").BytesIO(transcript.encode("utf-8")),
                    filename=f"ticket-{ticket['id']}.txt",
                )
                await log_channel.send(
                    embed=create_embed(
                        title=f"📕 Ticket #{ticket['id']} closed",
                        description=(
                            f"**Channel** : {channel.name}\n"
                            f"**Creator** : <@{ticket['creator_id']}>\n"
                            f"**Status** : closed"
                        ),
                    ),
                    file=file,
                )
            except Exception as exc:
                log.error("Failed to send ticket transcript: %s", exc)

        await db.close_ticket(ticket["id"])
        await channel.send(embed=create_embed(
            title="🔒 Ticket closed",
            description="This channel will be deleted in 5 seconds.",
        ))
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket #{ticket['id']} closed")
        except Exception as exc:
            log.error("Failed to delete ticket channel: %s", exc)


async def setup(bot: commands.Bot) -> None:
    cog = TicketsCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(ticket_group)