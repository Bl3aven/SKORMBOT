"""
SKORMAgency - Role selection cog
Button-based role selection with mutual exclusivity (Artist ↔ Agent)
and automatic alert messages in announcement channels.
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.utils import create_embed, get_channel_by_name, get_role_by_name

log = logging.getLogger("skorm.role_selection")


# === Configuration ===
ROLES_CHANNEL_NAME = "│claim-your-roles"

# Role → announcement channel mapping
ROLE_ALERT_MAP = {
    "Artist": "│artist-announcements",
    "Agent": "│agent-announcements",
    "Student": "│formation-announcements",
}

# Roles that are mutually exclusive (can't have more than one)
EXCLUSIVE_ROLES = {"Artist", "Agent"}


class RoleSelectionView(discord.ui.View):
    """Button view for role selection."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎤 Artist",
        style=discord.ButtonStyle.secondary,
        custom_id="skorm:role:artist",
    )
    async def artist(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_role(interaction, "Artist")

    @discord.ui.button(
        label="🤝 Agent",
        style=discord.ButtonStyle.secondary,
        custom_id="skorm:role:agent",
    )
    async def agent(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_role(interaction, "Agent")

    @discord.ui.button(
        label="🎓 Student",
        style=discord.ButtonStyle.secondary,
        custom_id="skorm:role:student",
    )
    async def student(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_role(interaction, "Student")

    async def _handle_role(
        self, interaction: discord.Interaction, role_name: str
    ) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Action unavailable.", ephemeral=True
            )
            return

        role = get_role_by_name(guild, role_name)
        if role is None:
            log.warning("Role %s not found in %s", role_name, guild.name)
            await interaction.response.send_message(
                f"❌ Role `{role_name}` not found.", ephemeral=True
            )
            return

        # Check mutual exclusivity: Artist ↔ Agent
        if role_name in EXCLUSIVE_ROLES:
            other_roles = EXCLUSIVE_ROLES - {role_name}
            for other_name in other_roles:
                other_role = get_role_by_name(guild, other_name)
                if other_role and other_role in member.roles:
                    await interaction.response.send_message(
                        f"❌ You can't be **{role_name}** and **{other_name}** at the same time.\n"
                        f"First remove the **{other_name}** role using the button below.",
                        ephemeral=True,
                    )
                    return

        # Toggle role
        if role in member.roles:
            await member.remove_roles(role, reason=f"Role selection: removed {role_name}")
            embed = create_embed(
                title=f"🔴 Role removed",
                description=f"You removed the **{role_name}** role.",
                color=0xFF0000,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            await member.add_roles(role, reason=f"Role selection: added {role_name}")

        # Send alert in announcement channel
        alert_channel_name = ROLE_ALERT_MAP.get(role_name)
        if alert_channel_name:
            alert_channel = get_channel_by_name(guild, alert_channel_name)
            if alert_channel:
                try:
                    alert_embed = create_embed(
                        title=f"🌩️ New member in {role_name}",
                        description=f"{member.mention} has joined the **{role_name}** group.",
                        color=0xFFFFFF,
                    )
                    await alert_channel.send(embed=alert_embed)
                except Exception as exc:
                    log.error("Failed to send alert in %s: %s", alert_channel_name, exc)

        embed = create_embed(
            title=f"✅ Role assigned",
            description=f"You got the **{role_name}** role.",
            color=0x00FF00,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RoleSelectionCog(commands.Cog):
    """Button-based role selection with alerts."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._initialised = False

    async def cog_load(self) -> None:
        self.bot.add_view(RoleSelectionView())

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._initialised:
            return
        self._initialised = True
        await self._send_role_selection_message()

    async def _send_role_selection_message(self) -> None:
        """Post the role selection embed with buttons in the roles channel."""
        for guild in self.bot.guilds:
            channel = get_channel_by_name(guild, ROLES_CHANNEL_NAME)
            if channel is None:
                continue

            # Check if message already exists
            existing_message = None
            async for message in channel.history(limit=20):
                if (
                    message.author == self.bot.user
                    and message.embeds
                    and message.embeds[0].title == "🌩️ Choisis ton parcours"
                ):
                    existing_message = message
                    break

            embed = create_embed(
                title="🌩️ Choose Your Path",
                description=(
                    "Select your role below to join the corresponding group.\n\n"
                    "🎤 **Artist** — Music production, DJ, social media\n"
                    "🤝 **Agent** — Booking, prospecting, management\n"
                    "🎓 **Student** — Courses, coaching, mentoring\n\n"
                    "⚠️ **Artist** and **Agent** are mutually exclusive.\n"
                    "You can add **Student** as a complement."
                ),
                color=0xFFFFFF,
            )

            view = RoleSelectionView()

            if existing_message is not None:
                try:
                    await existing_message.edit(embed=embed, view=view)
                    return
                except Exception as exc:
                    log.warning("Failed to edit role selection message: %s", exc)

            try:
                await channel.send(embed=embed, view=view)
            except Exception as exc:
                log.error("Failed to send role selection message: %s", exc)

    @app_commands.command(
        name="refresh_roles",
        description="Refreshes the role selection message (staff only).",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def refresh_roles(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._send_role_selection_message()
        await interaction.followup.send("✅ Role selection message refreshed.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleSelectionCog(bot))
