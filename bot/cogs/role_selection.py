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
                "❌ Action indisponible.", ephemeral=True
            )
            return

        role = get_role_by_name(guild, role_name)
        if role is None:
            log.warning("Role %s not found in %s", role_name, guild.name)
            await interaction.response.send_message(
                f"❌ Rôle `{role_name}` introuvable.", ephemeral=True
            )
            return

        # Check mutual exclusivity: Artist ↔ Agent
        if role_name in EXCLUSIVE_ROLES:
            other_roles = EXCLUSIVE_ROLES - {role_name}
            for other_name in other_roles:
                other_role = get_role_by_name(guild, other_name)
                if other_role and other_role in member.roles:
                    await interaction.response.send_message(
                        f"❌ Tu ne peux pas être **{role_name}** et **{other_name}** en même temps.\n"
                        f"Retire d'abord le rôle **{other_name}** avec le bouton ci-dessous.",
                        ephemeral=True,
                    )
                    return

        # Toggle role
        if role in member.roles:
            await member.remove_roles(role, reason=f"Role selection: removed {role_name}")
            embed = create_embed(
                title=f"🔴 Rôle retiré",
                description=f"Tu as retiré le rôle **{role_name}**.",
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
                        title=f"🌩️ Nouveau membre dans {role_name}",
                        description=f"{member.mention} a rejoint le groupe **{role_name}**.",
                        color=0xFFFFFF,
                    )
                    await alert_channel.send(embed=alert_embed)
                except Exception as exc:
                    log.error("Failed to send alert in %s: %s", alert_channel_name, exc)

        embed = create_embed(
            title=f"✅ Rôle attribué",
            description=f"Tu as obtenu le rôle **{role_name}**.",
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
        """Post the role selection embed with buttons in the roles channel.
        Reuses existing message if found, deletes duplicates."""
        for guild in self.bot.guilds:
            channel = get_channel_by_name(guild, ROLES_CHANNEL_NAME)
            if channel is None:
                continue

            # Find ALL existing role selection messages (French or old English title)
            existing_messages = []
            async for message in channel.history(limit=50):
                if (
                    message.author == self.bot.user
                    and message.embeds
                    and message.embeds[0].title in ("🌩️ Choisis ton parcours", "🌩️ Choose Your Path")
                ):
                    existing_messages.append(message)

            embed = create_embed(
                title="🌩️ Choisis ton parcours",
                description=(
                    "Sélectionne ton rôle ci-dessous pour rejoindre le groupe correspondant.\n\n"
                    "🎤 **Artist** — Production musicale, DJ, réseaux sociaux\n"
                    "🤝 **Agent** — Booking, prospection, gestion\n"
                    "🎓 **Student** — Cours, coaching, mentoring\n\n"
                    "⚠️ **Artist** et **Agent** sont exclusifs.\n"
                    "Tu peux ajouter **Student** en complément."
                ),
                color=0xFFFFFF,
            )

            view = RoleSelectionView()

            if existing_messages:
                # Keep the first message, delete duplicates
                keep_message = existing_messages[0]
                for dup in existing_messages[1:]:
                    try:
                        await dup.delete()
                        log.info("Deleted duplicate role selection message %s in %s", dup.id, guild.name)
                    except Exception as exc:
                        log.warning("Failed to delete duplicate message %s: %s", dup.id, exc)

                # Update the kept message
                try:
                    await keep_message.edit(embed=embed, view=view)
                    log.info("Updated existing role selection message %s in %s", keep_message.id, guild.name)
                    return
                except Exception as exc:
                    log.warning("Failed to edit role selection message: %s", exc)

            # No existing message — create new one
            try:
                new_message = await channel.send(embed=embed, view=view)
                log.info("Created new role selection message %s in %s", new_message.id, guild.name)
            except Exception as exc:
                log.error("Failed to send role selection message: %s", exc)

    @app_commands.command(
        name="refresh_roles",
        description="Rafraîchit le message de sélection de rôles (staff only).",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def refresh_roles(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self._send_role_selection_message()
        await interaction.followup.send("✅ Message de sélection de rôles rafraîchi.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleSelectionCog(bot))
